from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.api.events import require_api_key

router = APIRouter(tags=["discover"])

@router.get("/discover/models")
def list_models(
    request: Request,
    project_id: str = Query(...),
    db: Session = Depends(get_db),
):
    require_api_key(request)

    rows = db.execute(
        text("""
            SELECT DISTINCT project_id, model_id, endpoint
            FROM events
            WHERE project_id = :project_id
            ORDER BY model_id, endpoint
        """),
        {"project_id": project_id},
    ).mappings().all()

    return {"items": list(rows)}

@router.get("/discover/days")
def list_days(
    request: Request,
    project_id: str = Query(...),
    model_id: str = Query(...),
    endpoint: str = Query("predict"),
    db: Session = Depends(get_db),
):
    require_api_key(request)

    # day is computed in UTC
    rows = db.execute(
        text("""
            SELECT DISTINCT (timestamp AT TIME ZONE 'UTC')::date AS day
            FROM events
            WHERE project_id = :project_id
              AND model_id = :model_id
              AND endpoint = :endpoint
            ORDER BY day
        """),
        {"project_id": project_id, "model_id": model_id, "endpoint": endpoint},
    ).fetchall()

    return {"days": [str(r[0]) for r in rows]}
