import time
import random
import requests
from datetime import datetime, timezone

# -----------------------------
# Config
# -----------------------------
BASE_URL = "http://localhost:8000"
API_KEY = "demo-key"

HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,
}

RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
PROJECT = f"demo_project_{RUN_ID}"
MODEL = "demo_model_v1"
ENDPOINT = "predict"


# -----------------------------
# Helpers
# -----------------------------
def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def severity(psi: float) -> str:
    if psi < 0.10:
        return "OK"
    if psi < 0.25:
        return "WARN"
    return "ALERT"


# -----------------------------
# API calls
# -----------------------------
def ingest_events(n=200, drift=False):
    url = f"{BASE_URL}/api/v1/events"
    batch = []

    for _ in range(n):
        age = random.randint(18, 70)
        balance = random.uniform(0, 5000)

        if drift:
            age += 20
            balance += 3000

        batch.append({
            "project_id": PROJECT,
            "model_id": MODEL,
            "endpoint": ENDPOINT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latency_ms": random.randint(20, 140),
            "y_pred": random.choice([0, 1]),
            "y_proba": random.random(),
            "features": {
                "age": age,
                "balance": balance,
                "country": random.choice(["CA", "US", "UK"]),
            },
        })

    r = requests.post(url, json=batch, headers=HEADERS, timeout=15)
    r.raise_for_status()
    print(f"✅ Ingested {r.json()['inserted']} events")


def compute_metrics(day: str):
    url = f"{BASE_URL}/api/v1/metrics/compute"
    params = {
        "project_id": PROJECT,
        "model_id": MODEL,
        "endpoint": ENDPOINT,
        "day": day,
    }
    r = requests.post(url, params=params, headers={"X-API-Key": API_KEY}, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_metrics(day: str):
    url = f"{BASE_URL}/api/v1/metrics/daily"
    params = {
        "project_id": PROJECT,
        "model_id": MODEL,
        "endpoint": ENDPOINT,
        "day": day,
    }
    r = requests.get(url, params=params, headers={"X-API-Key": API_KEY}, timeout=15)
    r.raise_for_status()
    return r.json()


def capture_baseline(feature="age", n=200, n_bins=10):
    url = f"{BASE_URL}/api/v1/drift/baseline/capture"
    params = {
        "project_id": PROJECT,
        "model_id": MODEL,
        "endpoint": ENDPOINT,
        "feature": feature,
        "n": n,
        "n_bins": n_bins,
    }
    r = requests.post(url, params=params, headers={"X-API-Key": API_KEY}, timeout=15)
    r.raise_for_status()
    return r.json()


def compute_drift(day: str, feature="age"):
    url = f"{BASE_URL}/api/v1/drift/compute"
    params = {
        "project_id": PROJECT,
        "model_id": MODEL,
        "endpoint": ENDPOINT,
        "day": day,
        "feature": feature,
    }
    r = requests.post(url, params=params, headers={"X-API-Key": API_KEY}, timeout=15)
    r.raise_for_status()
    return r.json()

def compute_drift_all(day: str):
    url = f"{BASE_URL}/api/v1/drift/compute_all"
    params = {"project_id": PROJECT, "model_id": MODEL, "endpoint": ENDPOINT, "day": day}
    r = requests.post(url, params=params, headers={"X-API-Key": API_KEY}, timeout=15)
    r.raise_for_status()
    return r.json()


# -----------------------------
# Main demo flow
# -----------------------------
if __name__ == "__main__":
    day = today_utc()

    print("\n1️⃣ Sending normal traffic")
    ingest_events(n=200, drift=False)
    time.sleep(0.2)

    print("\n2️⃣ Capturing baselines (age, balance)")
    b1 = capture_baseline(feature="age", n=200, n_bins=10)
    print(f"✅ Baseline captured: age n={b1['n_baseline']}, bins={len(b1['baseline_probs'])}")

    b2 = capture_baseline(feature="balance", n=200, n_bins=10)
    print(f"✅ Baseline captured: balance n={b2['n_baseline']}, bins={len(b2['baseline_probs'])}")

    print("\n3️⃣ Sending drifted traffic")
    ingest_events(n=200, drift=True)
    time.sleep(0.2)

    print("\n4️⃣ Computing daily metrics")
    metrics = compute_metrics(day)

    print("\n📊 Daily Metrics Summary")
    print(f"- n_events: {metrics['n_events']}")
    print(f"- latency p50 / p95 (ms): {metrics['latency_p50_ms']:.1f} / {metrics['latency_p95_ms']:.1f}")
    print(f"- y_pred_rate: {metrics['y_pred_rate']:.3f}")
    print(f"- y_proba_mean: {metrics['y_proba_mean']:.3f}")

    age = metrics["feature_stats"].get("age", {})
    bal = metrics["feature_stats"].get("balance", {})
    if age:
        print(f"- age mean / std: {age['mean']:.2f} / {age['std']:.2f}")
    if bal:
        print(f"- balance mean / std: {bal['mean']:.2f} / {bal['std']:.2f}")

    print("\n5️⃣ Computing PSI drift")
    drift = compute_drift(day, feature="age")
    psi_value = drift["psi"]

    print("\n🚨 Drift Result")
    print(f"PSI(age) = {psi_value:.3f} → {severity(psi_value)}")

    print("\n6️⃣ Computing PSI drift (all numeric features)")
    dr = compute_drift_all(day)

    print("\n🚨 Drift Results (PSI)")
    for feat, payload in sorted(dr["psi"].items()):
        print(f"PSI({feat}) = {payload['psi']:.3f} → {payload['severity']} (n={payload['n']})")

    print(f"\nMax drift: {dr['max_psi_feature']} PSI={dr['max_psi']:.3f} → {dr['max_severity']}")
