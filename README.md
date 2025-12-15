# ml-guard


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
