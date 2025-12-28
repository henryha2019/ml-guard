from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.events import require_api_key
from app.core.config import settings
from app.db.session import get_db
from app.services.alerts import list_alerts
from app.services.slack import send_slack_message, SlackError

router = APIRouter(tags=["alerts"])


@router.post("/alerts/slack/test")
def slack_test(request: Request):
    require_api_key(request)
    try:
        send_slack_message("✅ ML Guard Slack test alert (webhook connected).")
        return {"ok": True, "slack_enabled": bool(settings.slack_enabled)}
    except SlackError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/alerts")
def get_alerts(
    request: Request,
    project_id: str | None = Query(None),
    model_id: str | None = Query(None),
    endpoint: str | None = Query(None),
    rule: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    require_api_key(request)

    rows = list_alerts(
        db,
        project_id=project_id,
        model_id=model_id,
        endpoint=endpoint,
        rule=rule,
        limit=limit,
    )

    return {
        "items": [
            {
                "id": r.id,
                "project_id": r.project_id,
                "model_id": r.model_id,
                "endpoint": r.endpoint,
                "day": str(r.day),
                "rule": r.rule,
                "severity": r.severity,
                "value": float(r.value),
                "threshold": float(r.threshold),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "payload": r.payload,
            }
            for r in rows
        ]
    }
