from __future__ import annotations

from typing import Optional, Dict, Any
import requests

from app.core.config import settings


class SlackError(RuntimeError):
    pass


def send_slack_message(
    text: str,
    *,
    webhook_url: Optional[str] = None,
    blocks: Optional[list[Dict[str, Any]]] = None,
) -> None:
    if not settings.slack_enabled:
        return

    url = webhook_url or settings.slack_webhook_url
    if not url:
        raise SlackError("SLACK_WEBHOOK_URL is not set")

    payload: Dict[str, Any] = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        resp = requests.post(url, json=payload, timeout=10)
    except requests.RequestException as e:
        raise SlackError(f"Slack request failed: {e}") from e

    if resp.status_code >= 300:
        raise SlackError(f"Slack webhook returned {resp.status_code}: {resp.text}")
