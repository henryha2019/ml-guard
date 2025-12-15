from fastapi import APIRouter, HTTPException, Request
from app.api.events import require_api_key
from app.services.slack import send_slack_message, SlackError
from app.core.config import settings

router = APIRouter(tags=["alerts"])

@router.post("/alerts/slack/test")
def slack_test(request: Request):
    require_api_key(request)
    try:
        send_slack_message(
            "✅ ML Guard Slack test alert (webhook connected).",
        )
        return {"ok": True, "slack_enabled": settings.slack_enabled}
    except SlackError as e:
        raise HTTPException(status_code=400, detail=str(e))
