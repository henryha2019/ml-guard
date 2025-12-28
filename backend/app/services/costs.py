from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import boto3
from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DailyCost


@dataclass(frozen=True)
class CostRow:
    project_id: str
    day: date
    service: str
    amount: float
    unit: str
    payload: Dict[str, Any]


def _ce_client():
    """
    Option A: local credentials.
    - If aws_profile set: boto3.Session(profile_name=...)
    - Cost Explorer endpoint is in us-east-1. :contentReference[oaicite:5]{index=5}
    """
    if settings.aws_profile:
        sess = boto3.Session(profile_name=settings.aws_profile)
        return sess.client("ce", region_name=settings.aws_ce_region)
    return boto3.client("ce", region_name=settings.aws_ce_region)


def _parse_amount(metric_obj: Dict[str, Any]) -> Tuple[float, str]:
    amt_str = (metric_obj or {}).get("Amount", "0")
    unit = (metric_obj or {}).get("Unit", "USD")
    try:
        return float(amt_str), unit
    except Exception:
        return 0.0, unit


def fetch_daily_costs_from_ce(
    *,
    day: date,
    metric: Optional[str] = None,
    group_by_service: bool = True,
) -> List[CostRow]:
    """
    Fetch daily costs from Cost Explorer for a single UTC date.

    Cost Explorer API expects TimePeriod as dates with Start inclusive / End exclusive. :contentReference[oaicite:6]{index=6}
    """
    metric = metric or settings.aws_ce_cost_metric
    start = day.isoformat()
    end = (day + timedelta(days=1)).isoformat()

    ce = _ce_client()

    kwargs: Dict[str, Any] = {
        "TimePeriod": {"Start": start, "End": end},
        "Granularity": "DAILY",
        "Metrics": [metric],
    }

    if group_by_service:
        kwargs["GroupBy"] = [{"Type": "DIMENSION", "Key": "SERVICE"}]

    resp = ce.get_cost_and_usage(**kwargs)
    results = resp.get("ResultsByTime", []) or []

    rows: List[CostRow] = []
    for r in results:
        # Daily results window
        groups = r.get("Groups", []) or []
        if not groups:
            # No grouping => one total number
            amt, unit = _parse_amount((r.get("Total") or {}).get(metric, {}))
            rows.append(
                CostRow(
                    project_id="",  # filled by caller
                    day=day,
                    service="TOTAL",
                    amount=amt,
                    unit=unit,
                    payload={"raw": r},
                )
            )
            continue

        for g in groups:
            keys = g.get("Keys", []) or []
            service = keys[0] if keys else "UNKNOWN"
            amt, unit = _parse_amount((g.get("Metrics") or {}).get(metric, {}))
            rows.append(
                CostRow(
                    project_id="",  # filled by caller
                    day=day,
                    service=service,
                    amount=amt,
                    unit=unit,
                    payload={"raw": g},
                )
            )

    # Also compute TOTAL from the grouped rows (more convenient for spike checks)
    if rows:
        unit = rows[0].unit
        total_amt = sum(x.amount for x in rows)
        rows.append(
            CostRow(
                project_id="",
                day=day,
                service="TOTAL",
                amount=float(total_amt),
                unit=unit,
                payload={"computed_total_from_services": True},
            )
        )

    return rows


def upsert_daily_costs(
    db: Session,
    *,
    project_id: str,
    day: date,
    rows: List[CostRow],
    overwrite: bool = True,
) -> Dict[str, Any]:
    """
    Store costs for (project_id, day).
    If overwrite=True, we delete existing rows for that day/project first.
    """
    if overwrite:
        db.execute(
            delete(DailyCost).where(
                DailyCost.project_id == project_id,
                DailyCost.day == day,
            )
        )
        db.commit()

    inserted = 0
    for row in rows:
        r = DailyCost(
            project_id=project_id,
            day=day,
            service=row.service,
            amount=row.amount,
            unit=row.unit,
            payload=row.payload or {},
        )
        db.add(r)
        inserted += 1

    db.commit()
    return {"inserted": inserted}


def pull_and_store_daily_costs(
    db: Session,
    *,
    project_id: str,
    day: date,
    metric: Optional[str] = None,
    overwrite: bool = True,
) -> Dict[str, Any]:
    rows = fetch_daily_costs_from_ce(day=day, metric=metric, group_by_service=True)
    # fill project_id in dataclass rows
    rows = [CostRow(project_id=project_id, day=r.day, service=r.service, amount=r.amount, unit=r.unit, payload=r.payload) for r in rows]
    res = upsert_daily_costs(db, project_id=project_id, day=day, rows=rows, overwrite=overwrite)

    total = next((x.amount for x in rows if x.service == "TOTAL"), None)
    unit = next((x.unit for x in rows if x.service == "TOTAL"), "USD")

    return {
        "project_id": project_id,
        "day": day.isoformat(),
        "metric": metric or settings.aws_ce_cost_metric,
        "rows": len(rows),
        "total": total,
        "unit": unit,
        "stored": res["inserted"],
    }


def list_daily_costs(
    db: Session,
    *,
    project_id: str,
    day: date,
) -> List[DailyCost]:
    q = (
        select(DailyCost)
        .where(DailyCost.project_id == project_id, DailyCost.day == day)
        .order_by(DailyCost.service.asc())
    )
    return list(db.execute(q).scalars().all())


def get_total_cost(
    db: Session,
    *,
    project_id: str,
    day: date,
) -> Optional[DailyCost]:
    q = select(DailyCost).where(
        DailyCost.project_id == project_id,
        DailyCost.day == day,
        DailyCost.service == "TOTAL",
    )
    return db.execute(q).scalars().first()


def trailing_average_total_cost(
    db: Session,
    *,
    project_id: str,
    day: date,
    lookback_days: int = 7,
) -> Optional[float]:
    start = day - timedelta(days=lookback_days)
    q = (
        select(func.avg(DailyCost.amount))
        .where(
            DailyCost.project_id == project_id,
            DailyCost.service == "TOTAL",
            DailyCost.day >= start,
            DailyCost.day < day,
        )
    )
    avg_val = db.execute(q).scalar_one_or_none()
    if avg_val is None:
        return None
    return float(avg_val)
