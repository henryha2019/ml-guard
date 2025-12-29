# ML Guard

**Lightweight ML monitoring, drift detection, and optional AWS cost tracking for small teams.**

ML Guard is a minimal, production-grade monitoring service for ML inference systems. It collects a single stream of inference events and derives **daily performance metrics**, **data drift signals**, **alerts**, and **(optionally) AWS Cost Explorer costs**—without requiring a full MLOps platform.

> Datadog-lite for ML systems: fast to integrate, low operational overhead, and clear signals.

---

## What you can do with ML Guard

* Detect **feature drift** (PSI for numeric features and frequency divergence for categorical features)
* Track **inference latency** (p50 / p95), prediction distribution statistics, and feature statistics
* Run a **background worker** that computes daily aggregates (timezone-aware)
* View results in a **Streamlit dashboard**
* Integrate via a small **Python SDK**
* Pull **AWS Cost Explorer** daily costs (best-effort, optional)

---

## Demo

![ML Guard demo](assets/demo.gif)

---

## Architecture

```text
ML App (batch/REST)
    |
    |  inference events
    v
ML Guard SDK  ----HTTP---->  FastAPI Backend  <----HTTP----  Dashboard (Streamlit)
                                  |
                                  | writes / reads
                                  v
                               PostgreSQL
                                  ^
                                  |
                           Background Worker
                     (daily metrics, drift, costs, alerts)
                                  |
                                  v
                         Slack / Email (optional)
```

---

## Quickstart (local, end-to-end)

### Prerequisites

* Docker + Docker Compose
* Python 3.10+ (only required if you run local scripts)

### 1) Start the stack

```bash
docker compose up --build -d
```

Backend health check:

```bash
curl -s http://localhost:8000/api/v1/health | python -m json.tool
```

### 2) Run the demo (generates events, captures a baseline, computes metrics and drift)

```bash
python ./backend/demo/quickstart.py
```

### 3) Open the dashboard

* Dashboard: `http://localhost:8501`
* API: `http://localhost:8000`

---

## Validate everything locally (recommended)

If `validation.sh` exists in the repository root:

```bash
./validation.sh
echo $?
```

**Pass criteria**

* Exit code is `0`
* Health endpoint returns `{"status":"ok"}`
* Demo or validation produces non-empty metrics and drift output for a generated project

---

## Event ingestion contract

ML Guard derives metrics, drift, and alerts from a single event schema:

```json
{
  "project_id": "proj_123",
  "model_id": "churn_model_v1",
  "endpoint": "predict",
  "timestamp": "2025-01-01T00:00:00Z",
  "latency_ms": 42,
  "y_pred": 1,
  "y_proba": 0.81,
  "features": {
    "age": 29,
    "balance": 1200.5,
    "country": "CA"
  }
}
```

From this stream, ML Guard computes:

* Daily latency p50 / p95
* Prediction distribution statistics (rate / mean)
* Daily feature statistics (mean / std and distributions)
* Daily drift (PSI or categorical divergence), when a baseline exists

---

## Drift detection model

* **Baselines are explicit windows** (captured from a stable period)
* **Numeric drift:** PSI with configurable bins
* **Categorical drift:** frequency divergence
* Drift is computed **per day** with **timezone-aware day semantics**
* Missing baselines are handled explicitly (drift returns `missing_baseline` rather than failing silently)

---

## AWS Cost Explorer integration (optional)

Costs are **best-effort**:

* If credentials are absent, the worker logs a warning and continues
* Costs can be pulled on demand via the API

Recommended AWS setup:

* Provide credentials via environment variables or mount `~/.aws` into containers (local development)
* Set regions:

  * `AWS_CE_REGION=us-east-1`
  * `AWS_DEFAULT_REGION=us-east-1`

To pull costs locally:

```bash
curl -s -X POST "http://localhost:8000/api/v1/costs/pull?project_id=<PROJECT_ID>&day=<YYYY-MM-DD>&overwrite=true" \
  -H "X-API-Key: demo-key" | python -m json.tool
```

Note: Daily totals can be extremely small (near zero) depending on account activity. ML Guard treats this as normal.

---

## SDK usage (minimal example)

```python
from ml_guard import MLGuardClient

client = MLGuardClient(
    base_url="http://localhost:8000",
    api_key="demo-key",
)

client.ingest_event(
    project_id="proj_123",
    model_id="model_v1",
    endpoint="predict",
    latency_ms=35,
    y_pred=1,
    y_proba=0.77,
    features={"age": 31, "balance": 1500.0, "country": "CA"},
)
```

The SDK is intentionally thin. It enforces request shapes and provides convenient wrappers around the API.

---

## Running services

```bash
make up           # start services (detached)
make dashboard    # start the dashboard (if separated)
make validate     # run validation.sh
make down         # tear down containers and volumes
```

---

## Project structure (current)

```text
ml-guard/
  backend/                 # FastAPI backend, worker, and demo
  sdk/                     # Python client SDK (ml_guard)
  dashboard/               # Streamlit UI
  docker-compose.yml
  docker-compose.ci.yml
  Dockerfile.smoke
  Makefile
  validation.sh
```

---

## Design decisions

* **Single event contract** minimizes integration friction and supports both batch and online inference
* **Timezone-aware daily aggregation** avoids partial-day and boundary issues
* **Explicit baseline capture** makes drift comparisons stable and explainable
* **Best-effort cost ingestion** prevents optional AWS dependencies from breaking core monitoring
* **SDK and dashboard layered over the API** enforce clean interfaces and improve testability

---

## Roadmap (future extensions)

* Alembic-first migrations everywhere (no implicit schema creation)
* Alert policy management (per-project thresholds and routing)
* Pagination and indexing for high-volume event tables
* Optional Prometheus exporter (without requiring Grafana)
* Deployment reference: ECS / App Runner + RDS + IAM (least privilege)

---

## License

This project is source-available for viewing and evaluation.

Commercial use, deployment, modification, or redistribution requires explicit permission from the author. See `LICENSE`.
