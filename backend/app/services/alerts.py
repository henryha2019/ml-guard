from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Alert


def create_alert_once(
    db: Session,
    *,
    project_id: str,
    model_id: str,
    endpoint: str,
    day: date,
    rule: str,
    severity: str,
    value: float,
    threshold: float,
    payload: Dict[str, Any],
) -> tuple[bool, Optional[Alert]]:
    """
    Create alert only once per (project/model/endpoint/day/rule).
    Returns (created, row). If already exists, returns (False, None).
    """
    row = Alert(
        project_id=project_id,
        model_id=model_id,
        endpoint=endpoint,
        day=day,
        rule=rule,
        severity=severity,
        value=float(value),
        threshold=float(threshold),
        payload=payload,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return True, row
    except IntegrityError:
        db.rollback()
        return False, None


def list_alerts(
    db: Session,
    *,
    project_id: str | None = None,
    model_id: str | None = None,
    endpoint: str | None = None,
    rule: str | None = None,
    limit: int = 50,
) -> list[Alert]:
    stmt = select(Alert).order_by(Alert.created_at.desc())
    if project_id:
        stmt = stmt.where(Alert.project_id == project_id)
    if model_id:
        stmt = stmt.where(Alert.model_id == model_id)
    if endpoint:
        stmt = stmt.where(Alert.endpoint == endpoint)
    if rule:
        stmt = stmt.where(Alert.rule == rule)
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())
