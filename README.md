# ForecastHub

ForecastHub is a multi-dashboard weather intelligence platform with:
- Daily Plan Copilot
- Outfit + Packing Assistant
- Health Alerts Generator
- Weather Anomaly Detector
- MLflow-backed model training and promotion workflow

## Stack

- Frontend: React + Vite (deploy on Vercel)
- API: FastAPI (deploy on Render)
- Database: Postgres (Supabase or Neon)
- Scheduler: GitHub Actions cron
- Model workflow: MLflow (tracking + model artifacts)

## Monorepo Layout

```text
forecast-hub/
├── api/                         # FastAPI backend
│   ├── app/
│   │   ├── routers/             # /v1/dashboard, /v1/jobs, /v1/models
│   │   ├── services/            # ingestion, insights, anomaly, and model workflow
│   │   ├── config.py            # environment config
│   │   ├── db.py                # SQLAlchemy engine/session
│   │   ├── models.py            # DB models including model_versions
│   │   ├── schemas.py           # response schemas
│   │   └── main.py              # app bootstrap
│   ├── requirements.txt
│   ├── .env.example
│   └── render.yaml
├── web/                         # React dashboard app
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── api/client.ts
│   │   └── App.tsx
│   ├── package.json
│   ├── .env.example
│   └── vercel.json
└── .github/workflows/
    ├── forecast_hub_scheduler.yml
    └── forecast_hub_model_training.yml
```

## Local Development

### 1. Run API

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### 2. Run Web

```bash
cd web
npm install
cp .env.example .env
npm run dev
```

## Environment Variables

### API (`api/.env`)

- `DATABASE_URL` (Supabase/Neon Postgres URL)
- `SUPABASE_DATABASE_URL` (optional override; if set, this is used instead of `DATABASE_URL`)
- `FRONTEND_ORIGIN` (Vercel domain, comma separated if multiple)
- `SCHEDULER_JOB_TOKEN` (shared secret for GitHub cron)
- `OPENAI_API_KEY` (optional)
- `MLFLOW_TRACKING_URI` (example: `file:./mlruns`)
- `MLFLOW_EXPERIMENT_NAME`
- `MLFLOW_MODEL_NAME`

### Web (`web/.env`)

- `VITE_API_BASE_URL` (Render API base URL)

## API Endpoints

- `GET /healthz`
- `GET /v1/dashboard/overview?location=Chicago`
- `GET /v1/dashboard/plan?location=Chicago&target_date=2026-03-04`
- `GET /v1/dashboard/outfit?location=Chicago&target_date=2026-03-04`
- `GET /v1/dashboard/health?location=Chicago&target_date=2026-03-04`
- `GET /v1/dashboard/anomalies?location=Chicago&window_days=7`
- `POST /v1/jobs/run-hourly` with `X-Job-Token`
- `POST /v1/jobs/train-model` with `X-Job-Token`
- `GET /v1/models/active`
- `GET /v1/models/versions`

## Deployment

### Render (API)

1. Create a Web Service from the repo.
2. Set Root Directory to `api`.
3. Build command: `pip install -r requirements.txt`.
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
5. Set env vars from `api/.env.example`.

## Postgres Migration (Neon -> Supabase)

Run from `api/`:

```bash
SOURCE_DATABASE_URL="<current_neon_or_postgres_url>" \
SUPABASE_DATABASE_URL="<supabase_postgres_url>" \
bash scripts/migrate_postgres_to_supabase.sh
```

Then set `SUPABASE_DATABASE_URL` in Render for the API service and redeploy.

### Vercel (Web)

1. Import repo and set Root Directory to `web`.
2. Set `VITE_API_BASE_URL` to your Render API URL.
3. Deploy.

### GitHub Actions Schedulers

Add repository secrets:
- `FORECASTHUB_API_BASE_URL` (e.g. `https://your-render-url.onrender.com`)
- `FORECASTHUB_SCHEDULER_JOB_TOKEN`

Workflows:
- `forecast_hub_scheduler.yml` (hourly ingestion/insights)
- `forecast_hub_model_training.yml` (daily MLflow training)
