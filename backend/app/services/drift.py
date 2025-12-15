from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import select, delete

from app.db.models import Event, FeatureBaseline, DailyDrift


def _day_range_utc(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _make_bins(values: List[float], n_bins: int = 10) -> List[float]:
    """Equal-width bin edges covering min..max (inclusive)."""
    if not values:
        raise ValueError("No values to bin")
    vmin = min(values)
    vmax = max(values)
    if vmin == vmax:
        # degenerate: add a tiny range so bins exist
        vmin -= 0.5
        vmax += 0.5
    width = (vmax - vmin) / n_bins
    edges = [vmin + i * width for i in range(n_bins)]
    edges.append(vmax)
    return edges


def _hist_probs(values: List[float], bin_edges: List[float]) -> List[float]:
    """Histogram probabilities given explicit bin edges (len = n_bins+1)."""
    n_bins = len(bin_edges) - 1
    counts = [0] * n_bins
    for x in values:
        # last bin includes right edge
        placed = False
        for i in range(n_bins):
            left = bin_edges[i]
            right = bin_edges[i + 1]
            if i == n_bins - 1:
                if left <= x <= right:
                    counts[i] += 1
                    placed = True
                    break
            else:
                if left <= x < right:
                    counts[i] += 1
                    placed = True
                    break
        # values can fall slightly outside due to float quirks; clamp
        if not placed:
            if x < bin_edges[0]:
                counts[0] += 1
            else:
                counts[-1] += 1

    total = sum(counts)
    if total == 0:
        return [0.0] * n_bins
    return [c / total for c in counts]


def psi(expected: List[float], actual: List[float], eps: float = 1e-6) -> float:
    """
    PSI = sum((a - e) * ln(a/e)) over bins.
    eps prevents log(0).
    """
    if len(expected) != len(actual):
        raise ValueError("expected and actual must have same length")
    total = 0.0
    for e, a in zip(expected, actual):
        e2 = max(float(e), eps)
        a2 = max(float(a), eps)
        total += (a2 - e2) * __import__("math").log(a2 / e2)
    return float(total)


@dataclass
class BaselineResult:
    project_id: str
    model_id: str
    endpoint: str
    feature: str
    n_baseline: int
    bin_edges: List[float]
    baseline_probs: List[float]


def capture_baseline(
    db: Session,
    project_id: str,
    model_id: str,
    endpoint: str,
    feature: str,
    n: int = 500,
    n_bins: int = 10,
    overwrite: bool = True,
) -> BaselineResult:
    stmt = (
        select(Event)
        .where(Event.project_id == project_id)
        .where(Event.model_id == model_id)
        .where(Event.endpoint == endpoint)
        .order_by(Event.timestamp.desc())
        .limit(n)
    )
    events = list(db.scalars(stmt).all())

    vals = []
    for e in events:
        v = (e.features or {}).get(feature)
        if _is_number(v):
            vals.append(float(v))

    if len(vals) < max(20, n_bins * 2):
        raise ValueError(f"Not enough numeric values for feature '{feature}'. Got {len(vals)}")

    edges = _make_bins(vals, n_bins=n_bins)
    probs = _hist_probs(vals, edges)

    if overwrite:
        db.execute(
            delete(FeatureBaseline).where(
                (FeatureBaseline.project_id == project_id)
                & (FeatureBaseline.model_id == model_id)
                & (FeatureBaseline.endpoint == endpoint)
                & (FeatureBaseline.feature == feature)
            )
        )

    row = FeatureBaseline(
        project_id=project_id,
        model_id=model_id,
        endpoint=endpoint,
        feature=feature,
        bin_edges=edges,
        baseline_probs=probs,
        n_baseline=len(vals),
    )
    db.add(row)
    db.commit()

    return BaselineResult(
        project_id=project_id,
        model_id=model_id,
        endpoint=endpoint,
        feature=feature,
        n_baseline=len(vals),
        bin_edges=edges,
        baseline_probs=probs,
    )


def compute_daily_psi(
    db: Session,
    project_id: str,
    model_id: str,
    endpoint: str,
    day: date,
    feature: str,
    overwrite: bool = True,
) -> dict:
    # Load baseline
    base_stmt = (
        select(FeatureBaseline)
        .where(FeatureBaseline.project_id == project_id)
        .where(FeatureBaseline.model_id == model_id)
        .where(FeatureBaseline.endpoint == endpoint)
        .where(FeatureBaseline.feature == feature)
    )
    baseline = db.scalars(base_stmt).first()
    if not baseline:
        raise ValueError(f"No baseline found for feature '{feature}'. Capture one first.")

    start, end = _day_range_utc(day)
    evt_stmt = (
        select(Event)
        .where(Event.project_id == project_id)
        .where(Event.model_id == model_id)
        .where(Event.endpoint == endpoint)
        .where(Event.timestamp >= start)
        .where(Event.timestamp < end)
    )
    events = list(db.scalars(evt_stmt).all())

    vals = []
    for e in events:
        v = (e.features or {}).get(feature)
        if _is_number(v):
            vals.append(float(v))

    if len(vals) < 10:
        raise ValueError(f"Not enough values for feature '{feature}' on {day}. Got {len(vals)}")

    actual_probs = _hist_probs(vals, list(baseline.bin_edges))
    score = psi(list(baseline.baseline_probs), actual_probs)

    # Upsert daily drift JSON
    drift_stmt = (
        select(DailyDrift)
        .where(DailyDrift.project_id == project_id)
        .where(DailyDrift.model_id == model_id)
        .where(DailyDrift.endpoint == endpoint)
        .where(DailyDrift.day == day)
    )
    row = db.scalars(drift_stmt).first()

    payload = {"psi": float(score), "n": len(vals)}

    if row is None:
        row = DailyDrift(
            project_id=project_id,
            model_id=model_id,
            endpoint=endpoint,
            day=day,
            psi={feature: payload},
        )
        db.add(row)
    else:
        psi_map = dict(row.psi or {})
        psi_map[feature] = payload
        row.psi = psi_map

    db.commit()

    return {
        "project_id": project_id,
        "model_id": model_id,
        "endpoint": endpoint,
        "day": str(day),
        "feature": feature,
        "psi": float(score),
        "n": len(vals),
    }

def compute_daily_psi_all(
    db: Session,
    project_id: str,
    model_id: str,
    endpoint: str,
    day: date,
    overwrite: bool = True,
) -> dict:
    """
    Compute PSI for all numeric features found in events.features for the given day.
    Baselines must already exist for each feature (capture_baseline endpoint).
    Stores results into DailyDrift.psi as:
      {"age": {"psi": 0.12, "n": 300}, "balance": {"psi": 0.34, "n": 300}}
    """
    # Load all baselines for this model/endpoint
    base_stmt = (
        select(FeatureBaseline)
        .where(FeatureBaseline.project_id == project_id)
        .where(FeatureBaseline.model_id == model_id)
        .where(FeatureBaseline.endpoint == endpoint)
    )
    baselines = list(db.scalars(base_stmt).all())
    baseline_map = {b.feature: b for b in baselines}

    if not baseline_map:
        raise ValueError("No baselines found. Capture at least one baseline first.")

    start, end = _day_range_utc(day)

    evt_stmt = (
        select(Event)
        .where(Event.project_id == project_id)
        .where(Event.model_id == model_id)
        .where(Event.endpoint == endpoint)
        .where(Event.timestamp >= start)
        .where(Event.timestamp < end)
    )
    events = list(db.scalars(evt_stmt).all())
    if not events:
        raise ValueError(f"No events found for {project_id}/{model_id}/{endpoint} on {day}")

    # Collect numeric values per feature
    values_by_feature: dict[str, list[float]] = {}
    for e in events:
        feats = e.features or {}
        for k, v in feats.items():
            if _is_number(v):
                values_by_feature.setdefault(k, []).append(float(v))

    # Compute PSI for numeric features that have a baseline
    results: dict[str, dict] = {}
    missing_baseline = []

    for feature, vals in values_by_feature.items():
        baseline = baseline_map.get(feature)
        if not baseline:
            missing_baseline.append(feature)
            continue
        if len(vals) < 10:
            # too few samples: skip (don’t error)
            continue

        actual_probs = _hist_probs(vals, list(baseline.bin_edges))
        score = psi(list(baseline.baseline_probs), actual_probs)
        results[feature] = {"psi": float(score), "n": len(vals)}

    if not results and missing_baseline:
        raise ValueError(
            f"No PSI computed. Missing baselines for: {', '.join(sorted(missing_baseline))}"
        )
    if not results:
        raise ValueError("No PSI computed (no numeric features with enough samples).")

    # Upsert daily drift row
    drift_stmt = (
        select(DailyDrift)
        .where(DailyDrift.project_id == project_id)
        .where(DailyDrift.model_id == model_id)
        .where(DailyDrift.endpoint == endpoint)
        .where(DailyDrift.day == day)
    )
    row = db.scalars(drift_stmt).first()

    if row is None:
        row = DailyDrift(
            project_id=project_id,
            model_id=model_id,
            endpoint=endpoint,
            day=day,
            psi=results,
        )
        db.add(row)
    else:
        if overwrite:
            row.psi = results
        else:
            psi_map = dict(row.psi or {})
            psi_map.update(results)
            row.psi = psi_map

    db.commit()

    return {
        "project_id": project_id,
        "model_id": model_id,
        "endpoint": endpoint,
        "day": str(day),
        "psi": results,
        "missing_baseline": sorted(missing_baseline),
    }


def classify_severity(psi_value: float) -> str:
    if psi_value < 0.10:
        return "OK"
    if psi_value < 0.25:
        return "WARN"
    return "ALERT"
