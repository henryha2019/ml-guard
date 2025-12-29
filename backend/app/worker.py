# backend/app/worker.py
from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.metrics import compute_daily_metrics
from app.services.drift import compute_daily_drift_all
from app.services.costs import pull_and_store_daily_costs


log = logging.getLogger("mlguard.worker")


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _today_in_tz(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def _discover_model_keys(db) -> list[tuple[str, str, str]]:
    """
    Return distinct (project_id, model_id, endpoint) found in events.
    """
    rows = db.execute(
        text(
            """
            SELECT DISTINCT project_id, model_id, endpoint
            FROM events
            ORDER BY project_id, model_id, endpoint
            """
        )
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def _discover_projects(db) -> list[str]:
    rows = db.execute(
        text(
            """
            SELECT DISTINCT project_id
            FROM events
            ORDER BY project_id
            """
        )
    ).fetchall()
    return [r[0] for r in rows]


def _has_any_baseline(db, project_id: str, model_id: str, endpoint: str) -> bool:
    """
    Drift requires at least one baseline row for this (project, model, endpoint).
    Use a cheap COUNT(*) to avoid calling drift compute that will raise.
    """
    n = db.execute(
        text(
            """
            SELECT COUNT(*) FROM feature_baselines
            WHERE project_id = :project_id
              AND model_id = :model_id
              AND endpoint = :endpoint
            """
        ),
        {"project_id": project_id, "model_id": model_id, "endpoint": endpoint},
    ).scalar_one()
    return int(n) > 0


def run_once(*, tz: str, day: date, overwrite: bool, drift_min_samples: int) -> None:
    """
    Compute metrics + drift (+ costs best-effort) for a single day across all discovered keys.
    """
    db = SessionLocal()
    try:
        keys = _discover_model_keys(db)
        projects = _discover_projects(db)

        if not keys:
            log.info("No events found yet; skipping compute.")
            return

        log.info("Discovered %d (project, model, endpoint) keys.", len(keys))

        # 1) Metrics (always safe)
        for (project_id, model_id, endpoint) in keys:
            try:
                res = compute_daily_metrics(
                    db,
                    project_id=project_id,
                    model_id=model_id,
                    endpoint=endpoint,
                    day=day,
                    tz=tz,
                    overwrite=overwrite,
                )
                log.info(
                    "metrics ok: %s/%s/%s day=%s n=%s",
                    project_id,
                    model_id,
                    endpoint,
                    day.isoformat(),
                    res.n_events,
                )
            except Exception as e:
                log.exception(
                    "metrics failed: %s/%s/%s day=%s err=%s",
                    project_id,
                    model_id,
                    endpoint,
                    day.isoformat(),
                    str(e),
                )

        # 2) Drift
        # Treat "no baselines yet" / "no events for day" / "not enough samples" as normal skips.
        for (project_id, model_id, endpoint) in keys:
            # Pre-check: skip drift if no baselines exist for this key.
            try:
                if not _has_any_baseline(db, project_id, model_id, endpoint):
                    log.info(
                        "drift skipped (no baselines): %s/%s/%s day=%s",
                        project_id,
                        model_id,
                        endpoint,
                        day.isoformat(),
                    )
                    continue
            except Exception as e:
                log.exception(
                    "drift baseline precheck failed: %s/%s/%s err=%s",
                    project_id,
                    model_id,
                    endpoint,
                    str(e),
                )
                continue

            try:
                res = compute_daily_drift_all(
                    db,
                    project_id=project_id,
                    model_id=model_id,
                    endpoint=endpoint,
                    day=day,
                    tz=tz,
                    min_samples=drift_min_samples,
                    overwrite=overwrite,
                )
                max_psi = float(res.get("max_psi") or 0.0)
                log.info(
                    "drift ok: %s/%s/%s day=%s max_psi=%.4f missing_baseline=%d",
                    project_id,
                    model_id,
                    endpoint,
                    day.isoformat(),
                    max_psi,
                    len(res.get("missing_baseline") or []),
                )

            except ValueError as e:
                msg = str(e)

                # Expected conditions in normal operation: do not spam stack traces.
                if "No baselines found" in msg:
                    log.info(
                        "drift skipped (no baselines): %s/%s/%s day=%s",
                        project_id,
                        model_id,
                        endpoint,
                        day.isoformat(),
                    )
                elif "No events found" in msg or "n_events" in msg:
                    log.info(
                        "drift skipped (no events for day): %s/%s/%s day=%s",
                        project_id,
                        model_id,
                        endpoint,
                        day.isoformat(),
                    )
                elif "min_samples" in msg or "Not enough" in msg or "insufficient" in msg:
                    log.info(
                        "drift skipped (insufficient samples): %s/%s/%s day=%s err=%s",
                        project_id,
                        model_id,
                        endpoint,
                        day.isoformat(),
                        msg,
                    )
                else:
                    log.exception(
                        "drift failed: %s/%s/%s day=%s err=%s",
                        project_id,
                        model_id,
                        endpoint,
                        day.isoformat(),
                        msg,
                    )

            except Exception as e:
                log.exception(
                    "drift failed: %s/%s/%s day=%s err=%s",
                    project_id,
                    model_id,
                    endpoint,
                    day.isoformat(),
                    str(e),
                )

        # 3) Costs (best-effort; may fail if AWS creds not present)
        for project_id in projects:
            try:
                cres = pull_and_store_daily_costs(
                    db,
                    project_id=project_id,
                    day=day,
                    overwrite=overwrite,
                )
                log.info(
                    "costs ok: %s day=%s total=%s %s",
                    project_id,
                    day.isoformat(),
                    cres.get("total"),
                    cres.get("unit"),
                )
            except Exception as e:
                # Intentionally not fatal; if creds/permissions aren't present, keep the worker alive.
                log.warning(
                    "costs skipped/failed (non-fatal): %s day=%s err=%s",
                    project_id,
                    day.isoformat(),
                    str(e),
                )

    finally:
        db.close()


def main() -> None:
    # Defaults: compute "yesterday" in the configured tz (avoids partial-day drift/metrics).
    tz = os.getenv("WORKER_TZ", "UTC")
    overwrite = os.getenv("WORKER_OVERWRITE", "true").lower() in ("1", "true", "yes")
    sleep_seconds = _env_int("WORKER_SLEEP_SECONDS", 300)  # 5 min
    drift_min_samples = _env_int("WORKER_DRIFT_MIN_SAMPLES", 10)

    # How many days back from "today" (in tz) to compute. Default 1 = yesterday.
    day_offset = _env_int("WORKER_DAY_OFFSET", 1)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

    log.info(
        "Worker starting: tz=%s overwrite=%s sleep=%ss day_offset=%s",
        tz,
        overwrite,
        sleep_seconds,
        day_offset,
    )

    while True:
        try:
            day = _today_in_tz(tz) - timedelta(days=day_offset)
            run_once(tz=tz, day=day, overwrite=overwrite, drift_min_samples=drift_min_samples)
        except Exception as e:
            log.exception("worker loop error: %s", str(e))

        time.sleep(max(5, sleep_seconds))


if __name__ == "__main__":
    main()
