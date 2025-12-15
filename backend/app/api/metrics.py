from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import DailyMetric
from app.core.config import settings
from app.api.events import require_api_key
from app.services.metrics import compute_daily_metrics

router = APIRouter(tags=["metrics"])

@router.post("/metrics/compute")
def compute(
    request: Request,
    project_id: str = Query(...),
    model_id: str = Query(...),
    endpoint: str = Query("predict"),
    day: date = Query(..., description="YYYY-MM-DD (UTC)"),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
):
    require_api_key(request)
    result = compute_daily_metrics(
        db=db,
        project_id=project_id,
        model_id=model_id,
        endpoint=endpoint,
        day=day,
        overwrite=overwrite,
    )
    return result.__dict__

@router.get("/metrics/daily")
def read_daily(
    request: Request,
    project_id: str,
    model_id: str,
    endpoint: str = "predict",
    day: date = Query(...),
    db: Session = Depends(get_db),
):
    require_api_key(request)

    stmt = (
        select(DailyMetric)
        .where(DailyMetric.project_id == project_id)
        .where(DailyMetric.model_id == model_id)
        .where(DailyMetric.endpoint == endpoint)
        .where(DailyMetric.day == day)
    )
    row = db.scalars(stmt).first()
    if not row:
        raise HTTPException(status_code=404, detail="No daily metrics found for that key")

    return {
        "project_id": row.project_id,
        "model_id": row.model_id,
        "endpoint": row.endpoint,
        "day": str(row.day),
        "n_events": row.n_events,
        "latency_p50_ms": row.latency_p50_ms,
        "latency_p95_ms": row.latency_p95_ms,
        "y_pred_rate": row.y_pred_rate,
        "y_proba_mean": row.y_proba_mean,
        "feature_stats": row.feature_stats,
    }
