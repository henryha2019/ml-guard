from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.events import require_api_key
from app.core.config import settings
from app.db.session import get_db
from app.services.alerts import create_alert_once
from app.services.costs import (
    get_total_cost,
    list_daily_costs,
    pull_and_store_daily_costs,
    trailing_average_total_cost,
)
from app.services.slack import send_slack_message

router = APIRouter(tags=["costs"])


@router.post("/costs/pull")
def pull_costs(
    request: Request,
    project_id: str = Query(...),
    day: date = Query(...),
    overwrite: bool = Query(True),
    metric: str | None = Query(None, description="Cost Explorer metric (default from settings)"),
    db: Session = Depends(get_db),
):
    """
    Pull and store daily costs from AWS Cost Explorer.

    Note: Cost Explorer is a global service with endpoint in us-east-1. :contentReference[oaicite:7]{index=7}
    """
    require_api_key(request)
    try:
        return pull_and_store_daily_costs(
            db,
            project_id=project_id,
            day=day,
            metric=metric,
            overwrite=overwrite,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cost pull failed: {e}")


@router.get("/costs/daily")
def daily_costs(
    request: Request,
    project_id: str = Query(...),
    day: date = Query(...),
    db: Session = Depends(get_db),
):
    require_api_key(request)
    rows = list_daily_costs(db, project_id=project_id, day=day)
    return {
        "project_id": project_id,
        "day": day.isoformat(),
        "rows": [
            {
                "service": r.service,
                "amount": float(r.amount),
                "unit": r.unit,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post("/costs/check_spike")
def check_cost_spike(
    request: Request,
    project_id: str = Query(...),
    day: date = Query(...),
    lookback_days: int = Query(7, ge=1, le=60),
    pct: float = Query(0.50, ge=0.05, le=5.0, description="Spike threshold as fraction (0.50 = +50%)"),
    min_abs_usd: float = Query(5.0, ge=0.0, le=100000.0, description="Minimum absolute increase to alert"),
    alert: bool = Query(True),
    slack: bool = Query(True),
    db: Session = Depends(get_db),
):
    """
    Compare TOTAL cost for day vs trailing average of prior lookback_days.
    If spike detected, optionally create alert (deduped) and send Slack.
    """
    require_api_key(request)

    total_row = get_total_cost(db, project_id=project_id, day=day)
    if total_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No stored TOTAL cost for {project_id} on {day.isoformat()}. Run /costs/pull first.",
        )

    avg = trailing_average_total_cost(db, project_id=project_id, day=day, lookback_days=lookback_days)
    if avg is None:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough historical TOTAL cost rows to compute trailing average (need prior days).",
        )

    value = float(total_row.amount)
    threshold_value = float(avg) * (1.0 + float(pct))

    is_spike = (value >= threshold_value) and ((value - float(avg)) >= float(min_abs_usd))

    # severity mapping
    severity = "OK"
    if is_spike:
        severity = "ALERT" if pct >= 0.25 else "WARN"

    alert_created = None
    alert_id = None
    slack_enabled = bool(settings.slack_enabled)
    slack_alert_sent = None
    slack_note = None

    payload = {
        "project_id": project_id,
        "day": day.isoformat(),
        "total_usd": value,
        "trailing_avg_usd": float(avg),
        "pct": float(pct),
        "min_abs_usd": float(min_abs_usd),
        "lookback_days": int(lookback_days),
        "computed_threshold_usd": threshold_value,
        "is_spike": is_spike,
    }

    if alert and is_spike:
        created, new_id = create_alert_once(
            db=db,
            project_id=project_id,
            model_id="__aws__",
            endpoint="__billing__",
            day=day,
            rule="cost_spike",
            severity=severity,
            value=value,
            threshold=threshold_value,
            payload=payload,
        )
        alert_created = created
        alert_id = new_id

        # Slack (optional)
        if slack and slack_enabled:
            try:
                send_slack_message(
                    text=(
                        f"🚨 ML Guard cost spike\n"
                        f"project={project_id} day={day.isoformat()}\n"
                        f"total=${value:.2f} avg=${float(avg):.2f} "
                        f"threshold=${threshold_value:.2f} (+{pct*100:.0f}%)"
                    )
                )
                slack_alert_sent = True
                slack_note = "Slack message sent."
            except Exception as e:
                slack_alert_sent = False
                slack_note = f"Slack send failed: {e}"
        else:
            slack_alert_sent = False
            slack_note = "Slack disabled; no message sent."
    else:
        alert_created = False if alert else None
        slack_alert_sent = False if (alert and slack) else None
        slack_enabled = False if (alert and slack) else None
        slack_note = "No alert: below threshold." if alert else None

    return {
        "project_id": project_id,
        "day": day.isoformat(),
        "total": value,
        "unit": total_row.unit,
        "trailing_avg": float(avg),
        "computed_threshold": threshold_value,
        "is_spike": is_spike,
        "severity": severity,
        "alert_created": alert_created,
        "alert_id": alert_id,
        "slack_alert_sent": slack_alert_sent,
        "slack_enabled": slack_enabled,
        "slack_note": slack_note,
        "params": {
            "lookback_days": lookback_days,
            "pct": pct,
            "min_abs_usd": min_abs_usd,
        },
    }
