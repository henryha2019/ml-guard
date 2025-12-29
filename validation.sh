#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------
# ML-Guard Local Validation Script
# -----------------------------------------

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_KEY="${API_KEY:-demo-key}"
TZ_IANA="${TZ_IANA:-America/Vancouver}"
N_BASELINE="${N_BASELINE:-200}"
N_DRIFT="${N_DRIFT:-200}"
DRIFT_THRESHOLD="${DRIFT_THRESHOLD:-0.25}"
COST_DAY_OFFSET="${COST_DAY_OFFSET:-1}"

HEADER_API_KEY=(-H "X-API-Key: ${API_KEY}")
HEADER_JSON=(-H "Content-Type: application/json")

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="${ROOT_DIR}/.tmp_validation"
mkdir -p "${TMP_DIR}"

log()  { printf "\n[%s] %s\n" "$(date '+%H:%M:%S')" "$*"; }
warn() { printf "\n[%s] WARN: %s\n" "$(date '+%H:%M:%S')" "$*"; }
die()  { printf "\n[%s] ERROR: %s\n" "$(date '+%H:%M:%S')" "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

http_status() {
  # Prints status code to stdout.
  # IMPORTANT: Never fail (prevents `set -e` from exiting on transient connect errors).
  curl -sS -o /dev/null -w "%{http_code}" "$@" || echo "000"
}

curl_json() {
  # prints body; exits nonzero on non-2xx
  local url="$1"; shift
  local tmp="${TMP_DIR}/resp.json"
  local code
  code="$(curl -sS -o "${tmp}" -w "%{http_code}" "$@" "${url}")" || true
  if [[ "${code}" != 2* ]]; then
    local body
    body="$(cat "${tmp}" 2>/dev/null || true)"
    die "Request failed (${code}) ${url} :: ${body}"
  fi
  cat "${tmp}"
}

wait_for_health() {
  local url="${BASE_URL}/api/v1/health"
  log "Waiting for backend health: ${url}"
  local tries=60
  for ((i=1; i<=tries; i++)); do
    local code
    code="$(http_status "${url}")"
    log "health check attempt ${i}/${tries}: HTTP ${code}"
    if [[ "${code}" == "200" ]]; then
      log "Backend is healthy."
      return 0
    fi
    sleep 1
  done
  die "Backend did not become healthy in time."
}

# -----------------------------------------
# Preconditions
# -----------------------------------------
require_cmd docker
require_cmd curl
require_cmd python
[[ -f "${ROOT_DIR}/docker-compose.yml" ]] || die "docker-compose.yml not found in project root: ${ROOT_DIR}"

# -----------------------------------------
# 0) Boot stack
# -----------------------------------------
log "Bringing up Docker Compose stack..."
(
  cd "${ROOT_DIR}"
  docker compose up --build -d
)

wait_for_health

# -----------------------------------------
# 1) Health + Auth checks
# -----------------------------------------
log "Validating /health..."
curl_json "${BASE_URL}/api/v1/health" | python -m json.tool >/dev/null
log "Health OK."

log "Validating auth enforcement (expect 401 without key)..."
code="$(http_status -X POST "${BASE_URL}/api/v1/metrics/compute?project_id=x&model_id=y&endpoint=predict&day=2025-12-27&tz=UTC")"
[[ "${code}" == "401" ]] || die "Expected 401 without API key, got ${code}"
log "Auth OK (401 without key)."

log "Validating auth success (expect 200 with key)..."
code="$(http_status -X POST "${BASE_URL}/api/v1/metrics/compute?project_id=x&model_id=y&endpoint=predict&day=2025-12-27&tz=UTC" "${HEADER_API_KEY[@]}")"
[[ "${code}" == "200" ]] || die "Expected 200 with API key, got ${code}"
log "Auth OK (200 with key)."

# -----------------------------------------
# 2) Generate demo traffic (baseline + drift) + capture baseline window
# -----------------------------------------
RUN_ID="$(python - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
PY
)"

PROJECT_ID="demo_project_${RUN_ID}"
MODEL_ID="demo_model_v1"
ENDPOINT="predict"

DAY_LOCAL="$(python - <<PY
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
print(datetime.now(timezone.utc).astimezone(ZoneInfo("${TZ_IANA}")).date().isoformat())
PY
)"

log "Using:"
log "  PROJECT_ID=${PROJECT_ID}"
log "  MODEL_ID=${MODEL_ID}"
log "  ENDPOINT=${ENDPOINT}"
log "  TZ=${TZ_IANA}"
log "  DAY_LOCAL=${DAY_LOCAL}"

BASELINE_JSON="${TMP_DIR}/baseline.json"
DRIFT_JSON="${TMP_DIR}/drift.json"
META_TXT="${TMP_DIR}/meta.txt"

log "Generating baseline batch (${N_BASELINE}) + drift batch (${N_DRIFT}) locally..."
python - <<PY
import json, random
from datetime import datetime, timezone
from pathlib import Path

PROJECT="${PROJECT_ID}"
MODEL="${MODEL_ID}"
ENDPOINT="${ENDPOINT}"

N_BASE=int("${N_BASELINE}")
N_DRIFT=int("${N_DRIFT}")

baseline=[]
drift=[]
tmin=None
tmax=None

def now_iso():
    return datetime.now(timezone.utc).isoformat()

for _ in range(N_BASE):
    ts = now_iso()
    dt = datetime.fromisoformat(ts)
    tmin = dt if tmin is None or dt < tmin else tmin
    tmax = dt if tmax is None or dt > tmax else tmax
    baseline.append({
        "project_id": PROJECT,
        "model_id": MODEL,
        "endpoint": ENDPOINT,
        "timestamp": ts,
        "latency_ms": random.randint(20, 140),
        "y_pred": random.choice([0,1]),
        "y_proba": random.random(),
        "features": {
            "age": random.randint(18, 70),
            "balance": random.uniform(0, 5000),
            "country": random.choice(["CA","US","UK"]),
        },
    })

for _ in range(N_DRIFT):
    ts = now_iso()
    drift.append({
        "project_id": PROJECT,
        "model_id": MODEL,
        "endpoint": ENDPOINT,
        "timestamp": ts,
        "latency_ms": random.randint(20, 140),
        "y_pred": random.choice([0,1]),
        "y_proba": random.random(),
        "features": {
            "age": random.randint(18, 70) + 20,
            "balance": random.uniform(0, 5000) + 3000,
            "country": random.choice(["CA","US","UK"]),
        },
    })

Path("${BASELINE_JSON}").write_text(json.dumps(baseline))
Path("${DRIFT_JSON}").write_text(json.dumps(drift))
Path("${META_TXT}").write_text(f"{tmin.isoformat()}\\n{tmax.isoformat()}\\n")
PY

T_MIN="$(sed -n '1p' "${META_TXT}")"
T_MAX="$(sed -n '2p' "${META_TXT}")"

T0="$(python - <<PY
from datetime import datetime, timedelta
t = datetime.fromisoformat("${T_MIN}")
print((t - timedelta(seconds=2)).isoformat())
PY
)"
T1="$(python - <<PY
from datetime import datetime, timedelta
t = datetime.fromisoformat("${T_MAX}")
print((t + timedelta(seconds=2)).isoformat())
PY
)"

log "Ingesting baseline events..."
curl_json "${BASE_URL}/api/v1/events" \
  -X POST "${HEADER_API_KEY[@]}" "${HEADER_JSON[@]}" \
  --data @"${BASELINE_JSON}" | python -m json.tool >/dev/null
log "Baseline ingest OK."

log "Capturing baselines (Option A timestamp window):"
log "  start_ts=${T0}"
log "  end_ts=${T1}"

for FEATURE in age balance country; do
  curl_json "${BASE_URL}/api/v1/drift/baseline/capture?project_id=${PROJECT_ID}&model_id=${MODEL_ID}&endpoint=${ENDPOINT}&feature=${FEATURE}&start_ts=$(python -c "import urllib.parse; print(urllib.parse.quote('''${T0}'''))")&end_ts=$(python -c "import urllib.parse; print(urllib.parse.quote('''${T1}'''))")&overwrite=true" \
    -X POST "${HEADER_API_KEY[@]}" | python -m json.tool >/dev/null
  log "Baseline captured: ${FEATURE}"
done

log "Ingesting drifted events..."
curl_json "${BASE_URL}/api/v1/events" \
  -X POST "${HEADER_API_KEY[@]}" "${HEADER_JSON[@]}" \
  --data @"${DRIFT_JSON}" | python -m json.tool >/dev/null
log "Drift ingest OK."

# -----------------------------------------
# 3) Discover models for the project
# -----------------------------------------
log "Validating discover/models..."
DISCOVER_OUT="$(curl_json "${BASE_URL}/api/v1/discover/models?project_id=${PROJECT_ID}" "${HEADER_API_KEY[@]}")"
echo "${DISCOVER_OUT}" | python -m json.tool
python - <<PY
import json, sys
d=json.loads('''${DISCOVER_OUT}''')
items=d.get("items", [])
ok=any((x.get("model_id")=="${MODEL_ID}" and x.get("endpoint")=="${ENDPOINT}") for x in items)
sys.exit(0 if ok else 1)
PY
log "discover/models OK."

# -----------------------------------------
# 4) Compute daily metrics (timezone-aware)
# -----------------------------------------
log "Validating metrics compute..."
METRICS_OUT="$(curl_json "${BASE_URL}/api/v1/metrics/compute?project_id=${PROJECT_ID}&model_id=${MODEL_ID}&endpoint=${ENDPOINT}&day=${DAY_LOCAL}&tz=${TZ_IANA}" \
  -X POST "${HEADER_API_KEY[@]}")"
echo "${METRICS_OUT}" | python -m json.tool
python - <<PY
import json, sys
m=json.loads('''${METRICS_OUT}''')
n=m.get("n_events", 0)
sys.exit(0 if n and n>0 else 1)
PY
log "metrics compute OK (n_events > 0)."

# -----------------------------------------
# 5) Compute drift_all + alerting
# -----------------------------------------
log "Validating drift compute_all (+ alerting)..."
DRIFT_OUT="$(curl_json "${BASE_URL}/api/v1/drift/compute_all?project_id=${PROJECT_ID}&model_id=${MODEL_ID}&endpoint=${ENDPOINT}&day=${DAY_LOCAL}&tz=${TZ_IANA}&alert=true&threshold=${DRIFT_THRESHOLD}" \
  -X POST "${HEADER_API_KEY[@]}")"
echo "${DRIFT_OUT}" | python -m json.tool

python - <<PY
import json, sys
d=json.loads('''${DRIFT_OUT}''')
psi=d.get("psi") or {}
needed={"age","balance","country"}
sys.exit(0 if needed.issubset(set(psi.keys())) else 1)
PY
log "drift compute_all OK (age/balance/country present)."

# -----------------------------------------
# 6) Alerts list
# -----------------------------------------
log "Validating alerts list (project-scoped)..."
ALERTS_OUT="$(curl_json "${BASE_URL}/api/v1/alerts?project_id=${PROJECT_ID}&limit=50" "${HEADER_API_KEY[@]}")"
echo "${ALERTS_OUT}" | python -m json.tool

python - <<PY
import json, sys
a=json.loads('''${ALERTS_OUT}''')
items = a.get("items") if isinstance(a, dict) else a
sys.exit(0 if items is not None else 1)
PY
log "alerts list OK."

# -----------------------------------------
# 7) Costs pull (best-effort)
# -----------------------------------------
COST_DAY="$(python - <<PY
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
d = datetime.now(timezone.utc).astimezone(ZoneInfo("${TZ_IANA}")).date() - timedelta(days=int("${COST_DAY_OFFSET}"))
print(d.isoformat())
PY
)"

log "Attempting costs pull (best-effort) for day=${COST_DAY}..."
set +e
COST_TMP="${TMP_DIR}/costs.json"
COST_CODE="$(curl -sS -o "${COST_TMP}" -w "%{http_code}" \
  -X POST "${BASE_URL}/api/v1/costs/pull?project_id=${PROJECT_ID}&day=${COST_DAY}&overwrite=true" \
  "${HEADER_API_KEY[@]}")"
set -e

if [[ "${COST_CODE}" == 2* ]]; then
  cat "${COST_TMP}" | python -m json.tool
  log "costs pull OK."
else
  warn "costs pull skipped/failed (${COST_CODE}). This is OK if AWS Cost Explorer credentials/permissions are not available."
  warn "response: $(cat "${COST_TMP}" 2>/dev/null || true)"
fi

# -----------------------------------------
# 8) Worker sanity (log tail)
# -----------------------------------------
log "Showing last 50 worker log lines for sanity..."
(
  cd "${ROOT_DIR}"
  docker compose logs --tail=50 worker || true
)

log "VALIDATION PASSED"
