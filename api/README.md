# ForecastHub API

FastAPI backend for ForecastHub multi-dashboard weather intelligence and MLflow model workflow.

## Local Run

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## Core Endpoints

- `GET /healthz`
- `GET /v1/dashboard/overview?location=Chicago`
- `GET /v1/dashboard/plan?location=Chicago&target_date=2026-03-04`
- `GET /v1/dashboard/outfit?location=Chicago&target_date=2026-03-04`
- `GET /v1/dashboard/health?location=Chicago&target_date=2026-03-04`
- `GET /v1/dashboard/anomalies?location=Chicago&window_days=7`

## Jobs and Model Workflow

- `POST /v1/jobs/run-hourly` with header `X-Job-Token`
- `POST /v1/jobs/train-model` with header `X-Job-Token`
- `GET /v1/models/active`
- `GET /v1/models/versions`

Training writes runs and artifacts to MLflow (`MLFLOW_TRACKING_URI`).

## Supabase Cutover

1. Create a Supabase project and copy its Postgres connection string.
2. Run the migration script from `api/`:

```bash
SOURCE_DATABASE_URL="<current_postgres_url>" \
SUPABASE_DATABASE_URL="<supabase_postgres_url>" \
bash scripts/migrate_postgres_to_supabase.sh
```

3. Point the API to Supabase in env:

```env
SUPABASE_DATABASE_URL=<supabase_postgres_url>
```

`SUPABASE_DATABASE_URL` is preferred over `DATABASE_URL` when both are set.
