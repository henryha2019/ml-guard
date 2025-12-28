# app/services/drift.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import select, delete

from app.db.models import Event, FeatureBaseline, DailyDrift


# -----------------------------
# Helpers
# -----------------------------
def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_categorical(x: Any) -> bool:
    return isinstance(x, str)


def _parse_iso_dt(s: str) -> datetime:
    """
    Parse ISO8601 datetime string, allowing 'Z'. Returns tz-aware datetime.
    """
    s2 = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _day_range_utc(day: date, tz: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(tz)
    start_local = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _make_bins(values: List[float], n_bins: int) -> List[float]:
    if not values:
        raise ValueError("No numeric values provided.")
    vmin = min(values)
    vmax = max(values)
    if vmin == vmax:
        vmin -= 0.5
        vmax += 0.5
    width = (vmax - vmin) / n_bins
    edges = [vmin + i * width for i in range(n_bins)]
    edges.append(vmax)
    return edges


def _hist_probs(values: List[float], bin_edges: List[float]) -> List[float]:
    n_bins = len(bin_edges) - 1
    counts = [0] * n_bins

    for x in values:
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
        if not placed:
            if x < bin_edges[0]:
                counts[0] += 1
            else:
                counts[-1] += 1

    total = sum(counts)
    if total == 0:
        return [0.0] * n_bins
    return [c / total for c in counts]


def _freq_probs(
    values: List[str],
    categories: List[str],
    other_bucket: bool = True,
) -> Tuple[List[str], List[float]]:
    cats = list(categories)
    if other_bucket and "__OTHER__" not in cats:
        cats.append("__OTHER__")

    counts = {c: 0 for c in cats}
    for v in values:
        if v in counts:
            counts[v] += 1
        else:
            if "__OTHER__" in counts:
                counts["__OTHER__"] += 1

    total = sum(counts.values())
    if total == 0:
        return cats, [0.0 for _ in cats]
    probs = [counts[c] / total for c in cats]
    return cats, probs


def psi(expected: List[float], actual: List[float], eps: float = 1e-6) -> float:
    """
    PSI = sum((a - e) * ln(a/e)) over bins.
    """
    if len(expected) != len(actual):
        raise ValueError("expected and actual must have the same length")
    import math

    total = 0.0
    for e, a in zip(expected, actual):
        e2 = max(float(e), eps)
        a2 = max(float(a), eps)
        total += (a2 - e2) * math.log(a2 / e2)
    return float(total)


def classify_severity(psi_value: float) -> str:
    if psi_value < 0.10:
        return "OK"
    if psi_value < 0.25:
        return "WARN"
    return "ALERT"


def _normalize_baseline(baseline_edges_json: Any, baseline_probs: List[float]) -> Dict[str, Any]:
    """
    Normalize baseline stored in FeatureBaseline.baseline_edges + baseline_probs.

    Supported formats:
      New numeric:
        {"type":"numeric","bin_edges":[...]}
      New categorical:
        {"type":"categorical","categories":[...],"other_bucket": true}
      Legacy numeric:
        [edge0, edge1, ..., edgeN]
    """
    if isinstance(baseline_edges_json, dict) and "type" in baseline_edges_json:
        btype = baseline_edges_json["type"]
        if btype == "numeric":
            return {
                "type": "numeric",
                "bin_edges": list(baseline_edges_json["bin_edges"]),
                "baseline_probs": list(baseline_probs),
            }
        if btype == "categorical":
            return {
                "type": "categorical",
                "categories": list(baseline_edges_json.get("categories", [])),
                "other_bucket": bool(baseline_edges_json.get("other_bucket", True)),
                "baseline_probs": list(baseline_probs),
            }
        raise ValueError(f"Unknown baseline type: {btype}")

    if isinstance(baseline_edges_json, list):
        # legacy numeric
        return {"type": "numeric", "bin_edges": list(baseline_edges_json), "baseline_probs": list(baseline_probs)}

    raise ValueError("Invalid baseline_edges format in DB")


# -----------------------------
# Results
# -----------------------------
@dataclass
class BaselineResult:
    project_id: str
    model_id: str
    endpoint: str
    feature: str
    feature_type: str
    n_baseline: int
    definition: Dict[str, Any]
    baseline_probs: List[float]


# -----------------------------
# Baseline capture
# -----------------------------
def capture_baseline(
    db: Session,
    project_id: str,
    model_id: str,
    endpoint: str,
    feature: str,
    n: int = 500,
    n_bins: int = 10,
    start_ts: Optional[str] = None,
    end_ts: Optional[str] = None,
    start_day: Optional[date] = None,
    end_day: Optional[date] = None,  # exclusive
    tz: str = "UTC",
    overwrite: bool = True,
    top_k_categories: int = 50,
) -> BaselineResult:
    """
    Capture baseline from:
      A) timestamps [start_ts, end_ts)
      B) day window [start_day, end_day) in tz (end_day exclusive)
      C) fallback: most recent n events

    Stores into FeatureBaseline.baseline_edges + baseline_probs.
    """
    stmt = (
        select(Event)
        .where(Event.project_id == project_id)
        .where(Event.model_id == model_id)
        .where(Event.endpoint == endpoint)
    )

    if start_ts or end_ts:
        if not (start_ts and end_ts):
            raise ValueError("If using timestamps, provide both start_ts and end_ts.")
        start = _parse_iso_dt(start_ts).astimezone(timezone.utc)
        end = _parse_iso_dt(end_ts).astimezone(timezone.utc)
        stmt = stmt.where(Event.timestamp >= start).where(Event.timestamp < end).order_by(Event.timestamp.asc())
    elif start_day and end_day:
        start, _ = _day_range_utc(start_day, tz)
        end, _ = _day_range_utc(end_day, tz)
        stmt = stmt.where(Event.timestamp >= start).where(Event.timestamp < end).order_by(Event.timestamp.asc())
    else:
        stmt = stmt.order_by(Event.timestamp.desc()).limit(n)

    events = list(db.scalars(stmt).all())
    if not events:
        raise ValueError("No events found for baseline capture window.")

    numeric_vals: List[float] = []
    cat_vals: List[str] = []
    for e in events:
        v = (e.features or {}).get(feature)
        if _is_number(v):
            numeric_vals.append(float(v))
        elif _is_categorical(v):
            cat_vals.append(v)

    # decide type
    if numeric_vals and (len(numeric_vals) >= len(cat_vals) or not cat_vals):
        if len(numeric_vals) < max(20, n_bins * 2):
            raise ValueError(f"Not enough numeric values for feature '{feature}'. Got {len(numeric_vals)}")
        edges = _make_bins(numeric_vals, n_bins=n_bins)
        probs = _hist_probs(numeric_vals, edges)
        definition = {"type": "numeric", "bin_edges": edges}
        feature_type = "numeric"
        n_used = len(numeric_vals)
    else:
        if len(cat_vals) < 20:
            raise ValueError(f"Not enough categorical values for feature '{feature}'. Got {len(cat_vals)}")
        counts: Dict[str, int] = {}
        for v in cat_vals:
            counts[v] = counts.get(v, 0) + 1
        cats_sorted = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        categories = [c for c, _ in cats_sorted[:top_k_categories]]

        cats_used, probs = _freq_probs(cat_vals, categories, other_bucket=True)
        definition = {"type": "categorical", "categories": categories, "other_bucket": True}
        feature_type = "categorical"
        n_used = len(cat_vals)

        # IMPORTANT: store probs aligned to categories + __OTHER__
        # definition stores only top categories; __OTHER__ is implied via other_bucket=True
        # baseline_probs length must match runtime cats_used length
        # We'll store categories INCLUDING __OTHER__ in baseline_edges for stable evaluation.
        definition = {"type": "categorical", "categories": cats_used, "other_bucket": True}

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
        feature_type=feature_type,
        n_baseline=n_used,
        baseline_edges=definition,   # <-- correct column name
        baseline_probs=probs,        # <-- correct column name
    )
    db.add(row)
    db.commit()

    return BaselineResult(
        project_id=project_id,
        model_id=model_id,
        endpoint=endpoint,
        feature=feature,
        feature_type=feature_type,
        n_baseline=n_used,
        definition=definition,
        baseline_probs=probs,
    )


# -----------------------------
# Drift compute (single feature)
# -----------------------------
def compute_daily_drift(
    db: Session,
    project_id: str,
    model_id: str,
    endpoint: str,
    day: date,
    feature: str,
    tz: str = "UTC",
    min_samples: int = 10,
) -> dict:
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

    base = _normalize_baseline(baseline.baseline_edges, list(baseline.baseline_probs))

    start, end = _day_range_utc(day, tz)
    evt_stmt = (
        select(Event)
        .where(Event.project_id == project_id)
        .where(Event.model_id == model_id)
        .where(Event.endpoint == endpoint)
        .where(Event.timestamp >= start)
        .where(Event.timestamp < end)
    )
    events = list(db.scalars(evt_stmt).all())

    if base["type"] == "numeric":
        vals: List[float] = []
        for e in events:
            v = (e.features or {}).get(feature)
            if _is_number(v):
                vals.append(float(v))
        if len(vals) < min_samples:
            raise ValueError(f"Not enough numeric samples for '{feature}' on {day} ({tz}). Got {len(vals)}")
        actual_probs = _hist_probs(vals, list(base["bin_edges"]))
        score = psi(list(base["baseline_probs"]), actual_probs)
        payload = {"psi": float(score), "n": len(vals), "type": "numeric", "severity": classify_severity(score)}
    else:
        vals: List[str] = []
        for e in events:
            v = (e.features or {}).get(feature)
            if _is_categorical(v):
                vals.append(v)
        if len(vals) < min_samples:
            raise ValueError(f"Not enough categorical samples for '{feature}' on {day} ({tz}). Got {len(vals)}")

        categories = list(base.get("categories", []))
        other_bucket = bool(base.get("other_bucket", True))
        cats_used, actual_probs = _freq_probs(vals, categories, other_bucket=other_bucket)

        score = psi(list(base["baseline_probs"]), actual_probs)
        payload = {
            "psi": float(score),
            "n": len(vals),
            "type": "categorical",
            "severity": classify_severity(score),
            "categories": cats_used,
        }

    # Store into DailyDrift.psi dict
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
            psi={feature: payload},
        )
        db.add(row)
    else:
        m = dict(row.psi or {})
        m[feature] = payload
        row.psi = m
    db.commit()

    return {
        "project_id": project_id,
        "model_id": model_id,
        "endpoint": endpoint,
        "day": str(day),
        "tz": tz,
        "feature": feature,
        **payload,
    }


# -----------------------------
# Drift compute (all baselined features)
# -----------------------------
def compute_daily_drift_all(
    db: Session,
    project_id: str,
    model_id: str,
    endpoint: str,
    day: date,
    tz: str = "UTC",
    min_samples: int = 10,
    overwrite: bool = True,
) -> dict:
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

    start, end = _day_range_utc(day, tz)
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
        raise ValueError(f"No events found for {project_id}/{model_id}/{endpoint} on {day} ({tz})")

    # collect observed values
    numeric_values: Dict[str, List[float]] = {}
    cat_values: Dict[str, List[str]] = {}
    seen_features: set[str] = set()

    for e in events:
        feats = e.features or {}
        for k, v in feats.items():
            seen_features.add(k)
            if _is_number(v):
                numeric_values.setdefault(k, []).append(float(v))
            elif _is_categorical(v):
                cat_values.setdefault(k, []).append(v)

    missing_baseline: List[str] = []
    skipped_low_sample: Dict[str, int] = {}
    results: Dict[str, Dict[str, Any]] = {}

    for feature in sorted(seen_features):
        b = baseline_map.get(feature)
        if not b:
            missing_baseline.append(feature)
            continue

        base = _normalize_baseline(b.baseline_edges, list(b.baseline_probs))

        if base["type"] == "numeric":
            vals = numeric_values.get(feature, [])
            if len(vals) < min_samples:
                skipped_low_sample[feature] = len(vals)
                continue
            actual_probs = _hist_probs(vals, list(base["bin_edges"]))
            score = psi(list(base["baseline_probs"]), actual_probs)
            results[feature] = {
                "psi": float(score),
                "n": len(vals),
                "type": "numeric",
                "severity": classify_severity(score),
            }
        else:
            vals = cat_values.get(feature, [])
            if len(vals) < min_samples:
                skipped_low_sample[feature] = len(vals)
                continue
            categories = list(base.get("categories", []))
            other_bucket = bool(base.get("other_bucket", True))
            cats_used, actual_probs = _freq_probs(vals, categories, other_bucket=other_bucket)
            score = psi(list(base["baseline_probs"]), actual_probs)
            results[feature] = {
                "psi": float(score),
                "n": len(vals),
                "type": "categorical",
                "severity": classify_severity(score),
                "categories": cats_used,
            }

    if not results:
        raise ValueError(
            f"No drift computed. missing_baseline={missing_baseline} skipped_low_sample={skipped_low_sample}"
        )

    # upsert DailyDrift row
    drift_stmt = (
        select(DailyDrift)
        .where(DailyDrift.project_id == project_id)
        .where(DailyDrift.model_id == model_id)
        .where(DailyDrift.endpoint == endpoint)
        .where(DailyDrift.day == day)
    )
    row = db.scalars(drift_stmt).first()
    if row is None:
        row = DailyDrift(project_id=project_id, model_id=model_id, endpoint=endpoint, day=day, psi=results)
        db.add(row)
    else:
        if overwrite:
            row.psi = results
        else:
            m = dict(row.psi or {})
            m.update(results)
            row.psi = m
    db.commit()

    max_feat = max(results.items(), key=lambda kv: kv[1]["psi"])[0]
    max_psi = float(results[max_feat]["psi"])
    max_sev = classify_severity(max_psi)

    return {
        "project_id": project_id,
        "model_id": model_id,
        "endpoint": endpoint,
        "day": str(day),
        "tz": tz,
        "psi": results,
        "missing_baseline": sorted(set(missing_baseline)),
        "skipped_low_sample": skipped_low_sample,
        "min_samples": int(min_samples),
        "max_psi_feature": max_feat,
        "max_psi": max_psi,
        "max_severity": max_sev,
    }
