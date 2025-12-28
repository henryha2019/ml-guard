# app/services/metrics.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy import select, delete

from app.db.models import Event, DailyMetric


def _percentile(values: List[float], p: float) -> Optional[float]:
    """Simple percentile (0-100). Returns None if empty."""
    if not values:
        return None
    vals = sorted(values)
    if len(vals) == 1:
        return float(vals[0])
    k = (len(vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    if f == c:
        return float(vals[f])
    d0 = vals[f] * (c - k)
    d1 = vals[c] * (k - f)
    return float(d0 + d1)


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _day_range(day: date, tz: str) -> tuple[datetime, datetime]:
    """
    Return [start, end) boundaries for a given local day in timezone `tz`,
    converted to UTC for DB filtering (timestamps stored with tzinfo).
    """
    zone = ZoneInfo(tz)
    start_local = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


@dataclass
class DailyMetricsResult:
    project_id: str
    model_id: str
    endpoint: str
    day: date
    tz: str
    n_events: int
    latency_p50_ms: Optional[float]
    latency_p95_ms: Optional[float]
    y_pred_rate: Optional[float]
    y_proba_mean: Optional[float]
    feature_stats: Dict[str, Dict[str, float]]


def compute_daily_metrics(
    db: Session,
    project_id: str,
    model_id: str,
    endpoint: str,
    day: date,
    *,
    tz: str = "UTC",
    overwrite: bool = True,
) -> DailyMetricsResult:
    start, end = _day_range(day, tz)

    stmt = (
        select(Event)
        .where(Event.project_id == project_id)
        .where(Event.model_id == model_id)
        .where(Event.endpoint == endpoint)
        .where(Event.timestamp >= start)
        .where(Event.timestamp < end)
    )
    events = list(db.scalars(stmt).all())

    n = len(events)

    latencies = [float(e.latency_ms) for e in events if e.latency_ms is not None]
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)

    y_preds = [e.y_pred for e in events if e.y_pred is not None]
    y_pred_rate = (sum(y_preds) / len(y_preds)) if y_preds else None

    y_probas = [float(e.y_proba) for e in events if e.y_proba is not None]
    y_proba_mean = (sum(y_probas) / len(y_probas)) if y_probas else None

    # Aggregate numeric feature stats
    per_feature: Dict[str, List[float]] = {}
    for e in events:
        for k, v in (e.features or {}).items():
            if _is_number(v):
                per_feature.setdefault(k, []).append(float(v))

    feature_stats: Dict[str, Dict[str, float]] = {}
    for k, vals in per_feature.items():
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        var = sum((x - mean) ** 2 for x in vals) / len(vals)
        std = var ** 0.5
        feature_stats[k] = {"mean": float(mean), "std": float(std)}

    if overwrite:
        db.execute(
            delete(DailyMetric).where(
                (DailyMetric.project_id == project_id)
                & (DailyMetric.model_id == model_id)
                & (DailyMetric.endpoint == endpoint)
                & (DailyMetric.day == day)
            )
        )

    row = DailyMetric(
        project_id=project_id,
        model_id=model_id,
        endpoint=endpoint,
        day=day,
        n_events=n,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        y_pred_rate=y_pred_rate,
        y_proba_mean=y_proba_mean,
        feature_stats=feature_stats,
    )

    db.add(row)
    db.commit()

    return DailyMetricsResult(
        project_id=project_id,
        model_id=model_id,
        endpoint=endpoint,
        day=day,
        tz=tz,
        n_events=n,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        y_pred_rate=y_pred_rate,
        y_proba_mean=y_proba_mean,
        feature_stats=feature_stats,
    )
