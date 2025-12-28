from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128), index=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    y_pred: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y_proba: Mapped[float | None] = mapped_column(Float, nullable=True)

    # arbitrary features payload
    features: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    __table_args__ = (
        UniqueConstraint("project_id", "model_id", "endpoint", "day", name="uq_daily_metrics"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128), index=True)

    day: Mapped[date] = mapped_column(Date, index=True)

    n_events: Mapped[int] = mapped_column(Integer, nullable=False)

    latency_p50_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_p95_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    y_pred_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    y_proba_mean: Mapped[float | None] = mapped_column(Float, nullable=True)

    feature_stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class FeatureBaseline(Base):
    __tablename__ = "feature_baselines"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "model_id",
            "endpoint",
            "feature",
            name="uq_feature_baseline",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128), index=True)

    feature: Mapped[str] = mapped_column(String(128), index=True)
    feature_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "numeric" | "categorical"

    n_baseline: Mapped[int] = mapped_column(Integer, nullable=False)

    # numeric: list[float] bin edges + list[float] probs
    # categorical: dict[str, float] probs (+ __OTHER__)
    baseline_edges: Mapped[list | None] = mapped_column(JSON, nullable=True)
    baseline_probs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class DailyDrift(Base):
    __tablename__ = "daily_drift"
    __table_args__ = (
        UniqueConstraint("project_id", "model_id", "endpoint", "day", name="uq_daily_drift"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128), index=True)

    day: Mapped[date] = mapped_column(Date, index=True)

    # store PSI map output: {feature: {...}}
    psi: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    max_psi_feature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    max_psi: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "model_id",
            "endpoint",
            "day",
            "rule",
            name="uq_alert_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128), index=True)

    day: Mapped[date] = mapped_column(Date, index=True)

    rule: Mapped[str] = mapped_column(String(64), index=True)  # e.g. "drift" / "cost_spike"
    severity: Mapped[str] = mapped_column(String(16), index=True)  # OK/WARN/ALERT

    value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)

    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


class DailyCost(Base):
    """
    Daily AWS cost snapshot, stored per (project, day, service).

    Notes:
    - Cost Explorer uses Start inclusive / End exclusive for TimePeriod. :contentReference[oaicite:3]{index=3}
    - Cost Explorer endpoint is us-east-1. :contentReference[oaicite:4]{index=4}
    """
    __tablename__ = "daily_costs"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "day",
            "service",
            name="uq_daily_costs",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    project_id: Mapped[str] = mapped_column(String(128), index=True)

    day: Mapped[date] = mapped_column(Date, index=True)

    # AWS Service name (e.g. "AmazonEC2") or "TOTAL"
    service: Mapped[str] = mapped_column(String(128), index=True)

    # Cost amount + unit (Cost Explorer returns strings; we store numeric)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="USD")

    # Raw CE response fragment for debugging (optional)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
