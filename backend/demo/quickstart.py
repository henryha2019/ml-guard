# demo/quickstart.py
import os
import time
import random
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# -----------------------------
# Config
# -----------------------------
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
API_KEY = "demo-key"

HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,
}

RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

# Option B: isolate each run (prevents mixing old events)
PROJECT = f"demo_project_{RUN_ID}"
MODEL = "demo_model_v1"
ENDPOINT = "predict"

# Keep local-day semantics (backend handles TZ slicing)
TZ = "America/Vancouver"

# Safety buffer for baseline timestamp window (covers request/DB timing jitter)
BASELINE_TS_BUFFER_SEC = 2


# -----------------------------
# Helpers
# -----------------------------
def today_tz_iso(tz: str) -> str:
    """
    Return the calendar day in the requested IANA timezone.
    This must NOT depend on the container's system timezone (often UTC in CI).
    """
    return datetime.now(timezone.utc).astimezone(ZoneInfo(tz)).date().isoformat()

def today_local_iso() -> str:
    """
    We use the system local date for the demo day. The backend performs timezone-aware slicing
    using TZ, so the API day value should reflect the user's local calendar day.
    """
    return datetime.now(timezone.utc).astimezone().date().isoformat()


def severity(psi: float) -> str:
    if psi < 0.10:
        return "OK"
    if psi < 0.25:
        return "WARN"
    return "ALERT"


def _raise_for_status_with_body(r: requests.Response, context: str) -> None:
    """
    requests.raise_for_status(), but includes response body (FastAPI error detail) for debugging.
    """
    if r.ok:
        return
    try:
        body = r.text
    except Exception:
        body = "<no body>"
    raise RuntimeError(f"{context} failed: {r.status_code} {body}")


# -----------------------------
# API calls
# -----------------------------
def ingest_events(n=200, drift=False):
    """
    Ingest a batch and return (min_ts_iso, max_ts_iso) for the timestamps generated in this batch.
    This is the key to a stable Option A baseline window.
    """
    url = f"{BASE_URL}/api/v1/events"
    batch = []

    t_min: datetime | None = None
    t_max: datetime | None = None

    for _ in range(n):
        ts_dt = datetime.now(timezone.utc)
        ts = ts_dt.isoformat()

        if t_min is None or ts_dt < t_min:
            t_min = ts_dt
        if t_max is None or ts_dt > t_max:
            t_max = ts_dt

        age = random.randint(18, 70)
        balance = random.uniform(0, 5000)

        if drift:
            age += 20
            balance += 3000

        batch.append(
            {
                "project_id": PROJECT,
                "model_id": MODEL,
                "endpoint": ENDPOINT,
                "timestamp": ts,
                "latency_ms": random.randint(20, 140),
                "y_pred": random.choice([0, 1]),
                "y_proba": random.random(),
                "features": {
                    "age": age,
                    "balance": balance,
                    "country": random.choice(["CA", "US", "UK"]),
                },
            }
        )

    r = requests.post(url, json=batch, headers=HEADERS, timeout=15)
    _raise_for_status_with_body(r, "Ingest")
    print(f"✅ Ingested {r.json()['inserted']} events")

    # These should never be None because n>=1 in our demo
    assert t_min is not None and t_max is not None
    return t_min.isoformat(), t_max.isoformat()


def compute_metrics(day: str, tz: str):
    url = f"{BASE_URL}/api/v1/metrics/compute"
    params = {
        "project_id": PROJECT,
        "model_id": MODEL,
        "endpoint": ENDPOINT,
        "day": day,
        "tz": tz,
    }
    r = requests.post(url, params=params, headers={"X-API-Key": API_KEY}, timeout=15)
    _raise_for_status_with_body(r, "Compute metrics")
    return r.json()


# Option A: stable baselines from explicit timestamp window
def capture_baseline_ts(
    feature: str,
    *,
    start_ts: str,
    end_ts: str,
    n_bins: int = 10,
    top_k_categories: int = 50,
):
    url = f"{BASE_URL}/api/v1/drift/baseline/capture"
    params = {
        "project_id": PROJECT,
        "model_id": MODEL,
        "endpoint": ENDPOINT,
        "feature": feature,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "n_bins": n_bins,
        "top_k_categories": top_k_categories,
        "overwrite": True,
    }
    r = requests.post(url, params=params, headers={"X-API-Key": API_KEY}, timeout=15)
    _raise_for_status_with_body(r, f"Capture baseline ({feature})")
    return r.json()


def compute_drift(day: str, feature: str, tz: str):
    url = f"{BASE_URL}/api/v1/drift/compute"
    params = {
        "project_id": PROJECT,
        "model_id": MODEL,
        "endpoint": ENDPOINT,
        "day": day,
        "feature": feature,
        "tz": tz,
    }
    r = requests.post(url, params=params, headers={"X-API-Key": API_KEY}, timeout=15)
    _raise_for_status_with_body(r, f"Compute drift ({feature})")
    return r.json()


def compute_drift_all(day: str, tz: str, alert: bool = True, threshold: float = 0.25):
    url = f"{BASE_URL}/api/v1/drift/compute_all"
    params = {
        "project_id": PROJECT,
        "model_id": MODEL,
        "endpoint": ENDPOINT,
        "day": day,
        "tz": tz,
        "alert": str(alert).lower(),
        "threshold": threshold,
    }
    r = requests.post(url, params=params, headers={"X-API-Key": API_KEY}, timeout=15)
    _raise_for_status_with_body(r, "Compute drift all")
    return r.json()


# -----------------------------
# Main demo flow
# -----------------------------
if __name__ == "__main__":
    day_local = today_tz_iso(TZ)

    print(f"\n🧪 Run ID: {RUN_ID}")
    print(f"🧩 Project: {PROJECT}")
    print(f"🕒 Using local timezone day semantics: tz={TZ}")
    print(f"📅 Demo day (local): {day_local}")

    # 1) Normal traffic (baseline source)
    print("\n1️⃣ Sending normal traffic")
    t_min, t_max = ingest_events(n=200, drift=False)
    time.sleep(0.2)

    # Expand window slightly for safety (Option A, stable)
    t0_dt = datetime.fromisoformat(t_min)
    t1_dt = datetime.fromisoformat(t_max)
    t0 = (t0_dt - timedelta(seconds=BASELINE_TS_BUFFER_SEC)).isoformat()
    t1 = (t1_dt + timedelta(seconds=BASELINE_TS_BUFFER_SEC)).isoformat()

    # 2) Capture baselines from the NORMAL-ONLY timestamp window (Option A)
    print("\n2️⃣ Capturing baselines from normal-traffic timestamp window (stable)")
    print(f"🧷 Baseline window: [{t0}, {t1})")

    b_age = capture_baseline_ts("age", start_ts=t0, end_ts=t1, n_bins=10)
    print(
        f"✅ Baseline captured: age type={b_age.get('feature_type')} n={b_age['n_baseline']} bins={len(b_age['baseline_probs'])}"
    )

    b_bal = capture_baseline_ts("balance", start_ts=t0, end_ts=t1, n_bins=10)
    print(
        f"✅ Baseline captured: balance type={b_bal.get('feature_type')} n={b_bal['n_baseline']} bins={len(b_bal['baseline_probs'])}"
    )

    b_cty = capture_baseline_ts("country", start_ts=t0, end_ts=t1, top_k_categories=10)
    print(f"✅ Baseline captured: country type={b_cty.get('feature_type')} n={b_cty['n_baseline']}")

    # 3) Drifted traffic (post-baseline)
    print("\n3️⃣ Sending drifted traffic")
    ingest_events(n=200, drift=True)
    time.sleep(0.2)

    # 4) Daily metrics (timezone-aware)
    print("\n4️⃣ Computing daily metrics (timezone-aware)")
    metrics = compute_metrics(day_local, tz=TZ)

    print("\n📊 Daily Metrics Summary")
    print(f"- n_events: {metrics['n_events']}")
    p50 = metrics.get("latency_p50_ms")
    p95 = metrics.get("latency_p95_ms")
    if p50 is None or p95 is None:
        print("- latency p50 / p95 (ms): N/A / N/A")
    else:
        print(f"- latency p50 / p95 (ms): {p50:.1f} / {p95:.1f}")
    print(f"- y_pred_rate: {metrics['y_pred_rate']:.3f}")
    print(f"- y_proba_mean: {metrics['y_proba_mean']:.3f}")

    age_stats = metrics.get("feature_stats", {}).get("age", {})
    bal_stats = metrics.get("feature_stats", {}).get("balance", {})
    if age_stats:
        print(f"- age mean / std: {age_stats['mean']:.2f} / {age_stats['std']:.2f}")
    if bal_stats:
        print(f"- balance mean / std: {bal_stats['mean']:.2f} / {bal_stats['std']:.2f}")

    # 5) Drift single feature
    print("\n5️⃣ Computing drift for a single feature (timezone-aware)")
    drift_age = compute_drift(day_local, feature="age", tz=TZ)
    psi_age = float(drift_age["psi"])

    print("\n🚨 Drift Result")
    print(f"PSI(age) = {psi_age:.3f} → {severity(psi_age)}")

    # 6) Drift all (numeric + categorical) with optional alerting
    print("\n6️⃣ Computing drift for all features (numeric + categorical) + alerting")
    dr = compute_drift_all(day_local, tz=TZ, alert=True, threshold=0.25)

    print("\n🚨 Drift Results")
    for feat, payload in sorted(dr["psi"].items()):
        print(f"- {feat} [{payload.get('type')}]: PSI={payload['psi']:.3f} → {payload['severity']} (n={payload['n']})")

    if dr.get("missing_baseline"):
        print(f"\n⚠️ Missing baselines: {dr['missing_baseline']}")
    if dr.get("skipped_low_sample"):
        print(f"\n⚠️ Skipped low-sample features (min={dr['min_samples']}): {dr['skipped_low_sample']}")

    print(f"\nMax drift: {dr['max_psi_feature']} PSI={dr['max_psi']:.3f} → {dr['max_severity']}")

    if dr.get("alert_created") is True:
        print(f"✅ Alert created: id={dr.get('alert_id')}")
    elif dr.get("alert_created") is False:
        note = dr.get("slack_note") or "Alert deduped or not created."
        print(f"ℹ️ {note}")
    else:
        print("ℹ️ Alerting not evaluated.")
