from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.db.models import Event

router = APIRouter(tags=["events"])

def require_api_key(request: Request):
    if not settings.enable_auth:
        return
    key = request.headers.get(settings.api_key_header)
    if not key or key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

class EventIn(BaseModel):
    project_id: str = Field(..., max_length=128)
    model_id: str = Field(..., max_length=128)
    endpoint: str = Field(..., max_length=128)

    timestamp: Optional[datetime] = None
    latency_ms: Optional[int] = None
    y_pred: Optional[int] = None
    y_proba: Optional[float] = None

    features: Dict[str, Any]

    def normalized_timestamp(self) -> datetime:
        ts = self.timestamp or datetime.now(timezone.utc)
        # Ensure timezone-aware
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

class IngestResponse(BaseModel):
    inserted: int

@router.get("/health")
def health():
    return {"status": "ok"}

@router.post("/events", response_model=IngestResponse)
def ingest_events(
    request: Request,
    payload: EventIn | List[EventIn],
    db: Session = Depends(get_db),
):
    require_api_key(request)

    events = payload if isinstance(payload, list) else [payload]

    rows: List[Event] = []
    for e in events:
        if not e.features:
            raise HTTPException(status_code=400, detail="features must be a non-empty object")

        rows.append(
            Event(
                project_id=e.project_id,
                model_id=e.model_id,
                endpoint=e.endpoint,
                timestamp=e.normalized_timestamp(),
                latency_ms=e.latency_ms,
                y_pred=e.y_pred,
                y_proba=e.y_proba,
                features=e.features,
            )
        )

    db.add_all(rows)
    db.commit()
    return IngestResponse(inserted=len(rows))
