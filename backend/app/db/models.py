from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, DateTime, Float, JSON, func, UniqueConstraint, Date
from datetime import date
from sqlalchemy import Boolean

class Base(DeclarativeBase):
    pass

class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128), index=True)

    timestamp: Mapped[DateTime] = mapped_column(DateTime(timezone=True), index=True)

    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y_pred: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y_proba: Mapped[float | None] = mapped_column(Float, nullable=True)

    features: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    __table_args__ = (
        UniqueConstraint("project_id", "model_id", "endpoint", "day", name="uq_daily_metrics_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128), index=True)

    day: Mapped["date"] = mapped_column(Date, index=True)

    n_events: Mapped[int] = mapped_column(Integer, nullable=False)

    latency_p50_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_p95_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    y_pred_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    y_proba_mean: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Per-feature numeric stats stored as JSON:
    # {"age": {"mean": 31.2, "std": 9.1}, "balance": {"mean": 402.0, "std": 112.3}}
    feature_stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class FeatureBaseline(Base):
    __tablename__ = "feature_baselines"
    __table_args__ = (
        UniqueConstraint("project_id", "model_id", "endpoint", "feature", name="uq_feature_baseline_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128), index=True)
    feature: Mapped[str] = mapped_column(String(128), index=True)

    # Stored histogram definition (bin edges + baseline proportions)
    bin_edges: Mapped[list] = mapped_column(JSON, nullable=False)
    baseline_probs: Mapped[list] = mapped_column(JSON, nullable=False)

    n_baseline: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DailyDrift(Base):
    __tablename__ = "daily_drift"
    __table_args__ = (
        UniqueConstraint("project_id", "model_id", "endpoint", "day", name="uq_daily_drift_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)

    # Store per-feature PSI results:
    # {"age": {"psi": 0.12, "n": 300}, "balance": {"psi": 0.34, "n": 300}}
    psi: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
