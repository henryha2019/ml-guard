Below is a **public-GitHub-optimized README**, plus:

1. a **Quickstart demo script** (copy-paste runnable)
2. a **clear architecture diagram** (Markdown / ASCII, GitHub-friendly)

This version is written to:

* attract recruiters
* reassure users it’s real
* keep scope tight and credible

---

# ML Guard

**Lightweight ML Monitoring & Cost Guard for Small Teams**

ML Guard is a minimal, production-grade MLOps monitoring service that tracks **model health, data drift, inference performance, and AWS costs** with almost zero setup.

It is built for teams that want **operational visibility** without running a full MLOps platform.

> Think: *Datadog-lite for machine learning systems.*

---

## ✨ Why This Exists

Most ML teams:

* don’t need Kubeflow or full-stack MLOps platforms
* don’t want to maintain Prometheus + Grafana
* **do** want to know when models drift or costs spike

ML Guard focuses on:

* **Actionable signals**
* **Low operational overhead**
* **Fast integration**
* **Clear cost ownership per model**

---

## 🚀 Core Features

### Model & Data Monitoring

* Input feature statistics (mean, std, distributions)
* Data drift detection (Population Stability Index)
* Prediction distribution monitoring
* Inference latency (p50 / p95)

### Cloud Cost Monitoring

* AWS Cost Explorer integration
* Cost attribution by **project / model / endpoint**
* Daily cost aggregation
* Cost spike detection

### Alerting

* Slack alerts
* Email alerts
* Threshold-based rules for drift, latency, and cost

---

## 🏗️ Architecture

```text
                        ┌────────────────────┐
                        │   ML Application   │
                        │ (batch or REST)    │
                        └─────────┬──────────┘
                                  │
                                  │ inference events
                                  ▼
                        ┌────────────────────┐
                        │   ML Guard SDK     │
                        │ (thin Python lib) │
                        └─────────┬──────────┘
                                  │ HTTP
                                  ▼
┌──────────────┐      ┌────────────────────┐      ┌──────────────┐
│ AWS Cost     │      │   FastAPI Backend  │      │  Dashboard   │
│ Explorer     │─────▶│  - ingest events   │◀────▶│ (Next/Dash)  │
└──────────────┘      │  - API & auth      │      └──────────────┘
                       └─────────┬──────────┘
                                 │
                                 │ async jobs
                                 ▼
                       ┌────────────────────┐
                       │ Background Worker  │
                       │ - metrics          │
                       │ - drift            │
                       │ - cost ingestion   │
                       │ - alerts           │
                       └─────────┬──────────┘
                                 │
                                 ▼
                       ┌────────────────────┐
                       │   PostgreSQL       │
                       │ events, metrics,   │
                       │ drift, costs       │
                       └────────────────────┘
```

---

## 🔁 How It Works

1. Your model sends inference events to ML Guard
2. Events are stored in PostgreSQL
3. Background jobs compute:

   * latency & prediction stats
   * feature distributions
   * drift scores
   * AWS cost attribution
4. Alerts fire when thresholds are exceeded
5. A minimal dashboard shows trends over time

---

## 📦 Event Ingestion (Core Contract)

Each inference emits a small JSON payload:

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

From this single stream, ML Guard derives:

* inference latency metrics
* prediction distributions
* feature statistics
* drift scores over time

---

## ⚡ Quickstart (Local Demo)

### Prerequisites

* Docker
* Docker Compose
* Python 3.10+

---

### 1️⃣ Start ML Guard locally

```bash
git clone https://github.com/your-username/ml-guard.git
cd ml-guard

cp .env.example .env
docker compose up --build
```

API will be available at:

```
http://localhost:8000
```

---

### 2️⃣ Send demo inference events

Create `demo/send_events.py`:

```python
import time
import random
import requests
from datetime import datetime

API_URL = "http://localhost:8000/api/v1/events"
API_KEY = "demo-key"

headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

for i in range(500):
    payload = {
        "project_id": "demo_project",
        "model_id": "demo_model_v1",
        "endpoint": "predict",
        "timestamp": datetime.utcnow().isoformat(),
        "latency_ms": random.randint(20, 120),
        "y_pred": random.choice([0, 1]),
        "y_proba": random.random(),
        "features": {
            "age": random.randint(18, 70),
            "balance": random.uniform(0, 5000),
            "country": random.choice(["CA", "US", "UK"])
        }
    }

    requests.post(API_URL, json=payload, headers=headers)
    time.sleep(0.05)

print("✅ Sent demo events")
```

Run it:

```bash
python demo/send_events.py
```

---

### 3️⃣ What you’ll see

* Events stored in PostgreSQL
* Aggregated latency & prediction stats
* Feature distributions per model
* Drift metrics after baseline capture
* (Optional) Slack alerts if thresholds are set

---

## 📊 Drift Detection

* Numeric features: PSI with configurable bins
* Categorical features: frequency divergence
* Baselines stored per model
* Drift tracked daily and compared to thresholds

---

## 💰 Cost Attribution (AWS)

AWS resources must be tagged with:

* `mlguard:project`
* `mlguard:model`
* `mlguard:endpoint`

ML Guard pulls AWS Cost Explorer data daily and attributes spend accordingly.

This enables:

* per-model cost tracking
* cost spike alerts
* operational cost accountability

---

## 🎯 Target Users

* Startups with early production models
* Indie SaaS builders
* Consulting teams
* Small ML teams without dedicated MLOps engineers

---

## 🧪 MVP Scope (Intentional)

* One model type (classification)
* Batch or REST inference
* Custom metrics (no Prometheus)
* AWS-only (v1)
* Minimal dashboard

---

## 🧠 Resume Signal

> **Built and deployed a production MLOps monitoring system with drift detection, cost attribution, alerting, and infrastructure-as-code on AWS.**

This project demonstrates:

* MLOps fundamentals
* Cloud cost awareness
* Monitoring & reliability thinking
* Production system design

---

## License

This project is source-available but not open source.

Viewing and evaluation are permitted.
Commercial use, deployment, modification, or redistribution
require explicit permission from the author.

See the LICENSE file for details.

---

```
ml-guard/
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── docker-compose.yml
├── Makefile
├── docs/
│   ├── architecture.md
│   ├── api.md
│   └── runbook.md
├── infra/                        # Terraform: VPC + ECS + RDS + SES/SNS + IAM
│   ├── README.md
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── versions.tf
│   └── modules/
│       ├── network/
│       ├── ecs_service/
│       ├── rds_postgres/
│       └── iam_cost_explorer/
├── backend/                      # FastAPI
│   ├── README.md
│   ├── pyproject.toml
│   ├── uv.lock (or requirements.txt)
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── logging.py
│   │   │   └── security.py
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   ├── session.py
│   │   │   └── models.py
│   │   ├── api/
│   │   │   ├── health.py
│   │   │   ├── projects.py
│   │   │   ├── models.py
│   │   │   ├── ingest.py
│   │   │   ├── metrics.py
│   │   │   ├── alerts.py
│   │   │   └── billing.py
│   │   ├── services/
│   │   │   ├── drift.py
│   │   │   ├── psi.py
│   │   │   ├── cost_explorer.py
│   │   │   ├── alert_router.py
│   │   │   └── scheduler.py
│   │   ├── workers/
│   │   │   └── jobs.py
│   │   └── schemas/
│   │       ├── ingest.py
│   │       ├── metrics.py
│   │       └── alerts.py
│   ├── tests/
│   └── Dockerfile
├── frontend/                     # minimal dashboard
│   ├── README.md
│   ├── package.json
│   ├── next.config.js
│   ├── tsconfig.json
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   └── lib/api.ts
│   └── Dockerfile
└── .github/
    └── workflows/
        ├── backend-ci.yml
        ├── frontend-ci.yml
        └── deploy.yml
```
