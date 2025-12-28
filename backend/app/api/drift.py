# app/api/drift.py
from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import DailyDrift
from app.api.events import require_api_key
from app.services.drift import (
    capture_baseline,
    compute_daily_drift,
    compute_daily_drift_all,
    classify_severity,
)
from app.services.alerts import create_alert_once
from app.services.slack import send_slack_message
from app.core.config import settings

router = APIRouter(tags=["drift"])


@router.post("/drift/baseline/capture")
def baseline_capture(
    request: Request,
    project_id: str,
    model_id: str,
    endpoint: str = "predict",
    feature: str = Query(...),
    # legacy
    n: int = Query(500, ge=1, le=50000),
    n_bins: int = Query(10, ge=2, le=200),
    # Option A: timestamp window
    start_ts: str | None = Query(None, description="ISO8601 start, e.g. 2025-12-28T00:00:00Z"),
    end_ts: str | None = Query(None, description="ISO8601 end (exclusive)"),
    # Option B: day window
    start_day: date | None = Query(None, description="Baseline start day (inclusive)"),
    end_day: date | None = Query(None, description="Baseline end day (exclusive)"),
    tz: str = Query("UTC", description="IANA timezone, e.g. America/Vancouver"),
    overwrite: bool = Query(True),
    top_k_categories: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    require_api_key(request)
    try:
        res = capture_baseline(
            db,
            project_id=project_id,
            model_id=model_id,
            endpoint=endpoint,
            feature=feature,
            n=n,
            n_bins=n_bins,
            start_ts=start_ts,
            end_ts=end_ts,
            start_day=start_day,
            end_day=end_day,
            tz=tz,
            overwrite=overwrite,
            top_k_categories=top_k_categories,
        )
        return {
            "project_id": res.project_id,
            "model_id": res.model_id,
            "endpoint": res.endpoint,
            "feature": res.feature,
            "feature_type": res.feature_type,
            "n_baseline": res.n_baseline,
            "definition": res.definition,
            "baseline_probs": res.baseline_probs,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/drift/compute")
def compute_one(
    request: Request,
    project_id: str,
    model_id: str,
    endpoint: str = "predict",
    day: date = Query(...),
    feature: str = Query(...),
    tz: str = Query("UTC", description="IANA timezone, e.g. America/Vancouver"),
    min_samples: int = Query(10, ge=1, le=100000),
    db: Session = Depends(get_db),
):
    require_api_key(request)
    try:
        return compute_daily_drift(
            db,
            project_id=project_id,
            model_id=model_id,
            endpoint=endpoint,
            day=day,
            feature=feature,
            tz=tz,
            min_samples=min_samples,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/drift/compute_all")
def compute_all(
    request: Request,
    project_id: str,
    model_id: str,
    endpoint: str = "predict",
    day: date = Query(...),
    tz: str = Query("UTC", description="IANA timezone, e.g. America/Vancouver"),
    min_samples: int = Query(10, ge=1, le=100000),
    overwrite: bool = Query(True),
    alert: bool = Query(False),
    threshold: float = Query(0.25, ge=0.0),
    db: Session = Depends(get_db),
):
    require_api_key(request)

    try:
        result = compute_daily_drift_all(
            db,
            project_id=project_id,
            model_id=model_id,
            endpoint=endpoint,
            day=day,
            tz=tz,
            min_samples=min_samples,
            overwrite=overwrite,
        )

        alert_created = None
        alert_id = None
        slack_alert_sent = None
        slack_note = None
        slack_enabled = None

        if alert:
            max_psi = float(result["max_psi"])
            sev = classify_severity(max_psi)
            slack_enabled = bool(getattr(settings, "slack_enabled", False))

            if max_psi >= float(threshold):
                created, row = create_alert_once(
                    db,
                    project_id=project_id,
                    model_id=model_id,
                    endpoint=endpoint,
                    day=day,
                    rule="drift",
                    severity=sev,
                    value=max_psi,
                    threshold=float(threshold),
                    payload=result,
                )
                alert_created = created
                alert_id = row.id if row else None

                if not slack_enabled:
                    slack_alert_sent = False
                    slack_note = "Slack disabled; no message sent."
                else:
                    try:
                        send_slack_message(
                            text=(
                                f"ML Guard drift alert: {project_id}/{model_id}/{endpoint} "
                                f"day={day} tz={tz} max_feature={result['max_psi_feature']} "
                                f"psi={max_psi:.3f} severity={sev} threshold={threshold}"
                            )
                        )
                        slack_alert_sent = True
                        slack_note = "Slack message sent."
                    except Exception as se:
                        slack_alert_sent = False
                        slack_note = str(se)
            else:
                alert_created = False
                alert_id = None
                slack_alert_sent = False
                slack_note = "No alert: max_psi below threshold."

        result.update(
            {
                "alert_created": alert_created,
                "alert_id": alert_id,
                "slack_alert_sent": slack_alert_sent,
                "slack_enabled": slack_enabled,
                "slack_note": slack_note,
                "threshold": float(threshold),
            }
        )
        return result

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/drift/daily")
def read_daily(
    request: Request,
    project_id: str,
    model_id: str,
    endpoint: str = "predict",
    day: date = Query(...),
    db: Session = Depends(get_db),
):
    """
    Raw stored DailyDrift row (per-feature JSON), useful for UI.
    """
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
        return None
    return {
        "project_id": row.project_id,
        "model_id": row.model_id,
        "endpoint": row.endpoint,
        "day": str(row.day),
        "psi": row.psi,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
