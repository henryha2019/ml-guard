from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import DailyDrift
from app.api.events import require_api_key
from app.services.drift import capture_baseline, compute_daily_psi

router = APIRouter(tags=["drift"])

@router.post("/drift/baseline/capture")
def baseline_capture(
    request: Request,
    project_id: str = Query(...),
    model_id: str = Query(...),
    endpoint: str = Query("predict"),
    feature: str = Query(..., description="numeric feature key inside features{}"),
    n: int = Query(500, ge=50, le=50000),
    n_bins: int = Query(10, ge=5, le=50),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
):
    require_api_key(request)
    try:
        result = capture_baseline(
            db=db,
            project_id=project_id,
            model_id=model_id,
            endpoint=endpoint,
            feature=feature,
            n=n,
            n_bins=n_bins,
            overwrite=overwrite,
        )
        return result.__dict__
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/drift/compute")
def drift_compute(
    request: Request,
    project_id: str = Query(...),
    model_id: str = Query(...),
    endpoint: str = Query("predict"),
    day: date = Query(...),
    feature: str = Query(...),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
):
    require_api_key(request)
    try:
        return compute_daily_psi(
            db=db,
            project_id=project_id,
            model_id=model_id,
            endpoint=endpoint,
            day=day,
            feature=feature,
            overwrite=overwrite,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/drift/daily")
def drift_daily(
    request: Request,
    project_id: str,
    model_id: str,
    endpoint: str = "predict",
    day: date = Query(...),
    db: Session = Depends(get_db),
):
    require_api_key(request)

    stmt = (
        select(DailyDrift)
        .where(DailyDrift.project_id == project_id)
        .where(DailyDrift.model_id == model_id)
        .where(DailyDrift.endpoint == endpoint)
        .where(DailyDrift.day == day)
    )
    row = db.scalars(stmt).first()
    if not row:
        raise HTTPException(status_code=404, detail="No drift computed for that key")
    return {
        "project_id": row.project_id,
        "model_id": row.model_id,
        "endpoint": row.endpoint,
        "day": str(row.day),
        "psi": row.psi,
    }
