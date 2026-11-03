# TiffinConnect

TiffinConnect connects hostel students with local home cooks. It includes student, cook, and admin experiences, a FastAPI API, PostgreSQL/SQLite support, and locally run recommendation and demand forecasting models.

## Features

- Student registration/login, meal search and dietary filters, portion and weekly/monthly ordering, order history, recommendations, and verified-order reviews.
- Cook menu management, stock tracking, order-status updates, sales summaries, and a seven-day demand forecast.
- Admin platform summary. Public registration is limited to students and cooks.
- Local development can run the TensorFlow LSTM demand forecaster. Forecasting is intentionally disabled on the free Render profile because its 512 MB RAM limit is not suitable for TensorFlow. The free deployment still supports meal recommendations.
- The demand model is trained and evaluated on synthetic data; its score is not real-world accuracy or operational advice.

## Local development (Windows PowerShell)

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements-ml.txt
cd backend
..\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. API health check: http://localhost:8000/api/health. Local interactive docs: http://localhost:8000/docs.

Local development uses SQLite and seeds demo accounts on first startup:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@tiffinconnect.com` | `admin123` |
| Student | `arjun@student.tiffin` | `student123` |
| Cook | `asha@cook.tiffin` | `cook123` |

These are demo credentials only. Production rejects demo-data seeding and starts without demo users. Configure an initial administrator with the one-time `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` (at least 12 characters), and optional `BOOTSTRAP_ADMIN_NAME` environment variables. Once the service starts and the admin can log in, remove the bootstrap variables; the account remains in the database.

## Free deployment profile

The included [Render Blueprint](./render.yaml) deploys the API to Render Free, and [frontend/vercel.json](./frontend/vercel.json) configures the Vite frontend for Vercel. Use Neon Free for PostgreSQL instead of Render Postgres.

This combination is suitable for a public academic demo, **not an always-on production service**. Free Render services have 512 MB RAM, sleep after 15 minutes without traffic, and lose local files on restart. Neon Free suspends compute after inactivity. Free limits and policies can change; check the [Render Free limitations](https://render.com/docs/free), [Neon pricing](https://neon.com/pricing), and [Vercel Hobby terms](https://vercel.com/legal/terms) before deploying.

### 1. Create a Neon database

1. Create a free project at [Neon](https://neon.tech/).
2. In the Neon Console, select **Connect** and copy the **pooled** connection string (the hostname contains `-pooler`). Keep `sslmode=require` and other query parameters intact.
3. Keep the connection string private. You will set it as `DATABASE_URL` in Render; do not commit it to GitHub.

### 2. Deploy the API on Render

1. In Render, choose **New → Blueprint** and connect `oshinde410/TiffinConnect`.
2. Render reads `render.yaml` and creates the `tiffinconnect-api` web service. Supply the Neon pooled URL for `DATABASE_URL`.
3. Set `CORS_ORIGINS` to the exact Vercel site origin, e.g. `https://tiffinconnect.vercel.app` (no path or trailing slash). You can update it after Vercel gives you the final domain.
4. The Blueprint generates a private `TIFFIN_SECRET`; do not replace it with a short or public value.
5. To initialize the admin, add `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`, and optionally `BOOTSTRAP_ADMIN_NAME` in the Render service's environment settings and redeploy. Remove the bootstrap variables after the admin account is created.
6. Wait for the deploy to become live. Check `https://<your-render-service>.onrender.com/api/health`.

The free profile sets `ENABLE_DEMAND_FORECAST=false` and does not install TensorFlow. For the forecast, use a paid service with adequate memory, change its build command to `pip install -r requirements-ml.txt`, and set `ENABLE_DEMAND_FORECAST=true`. Model files are stored under `backend/models` by default; configure `MODEL_DIR` to a persistent mounted path if you need to preserve the trained model across restarts.

### 3. Deploy the frontend on Vercel

1. Import `oshinde410/TiffinConnect` into Vercel.
2. Set the project **Root Directory** to `frontend`.
3. Add the environment variable `VITE_API_BASE_URL=https://<your-render-service>.onrender.com/api` for Production (and Preview only if those URLs are included in backend CORS).
4. Deploy. Add the resulting Vercel origin to Render's `CORS_ORIGINS` if it differs from the value set earlier.

Vercel Hobby is free but its current terms restrict use to personal or non-commercial projects. Do not use Hobby for a commercial meal marketplace.

## Is Vercel + Render the right free choice?

**Yes, with Neon for the database and the constraints above.** Use Vercel for the static React/Vite frontend, Render for FastAPI, and Neon for Postgres. This avoids SQLite on an ephemeral server and avoids Render's free Postgres database, which currently expires after 30 days.

As checked on November 3, 2026, Neon Free lists 1 GB storage and scale-to-zero compute; Render Free web services sleep after 15 idle minutes and provide 512 MB RAM; Vercel Hobby is $0 but restricted to personal/non-commercial use. This means the app can be demonstrated free, but may have a cold start, a paused database after inactivity, limited memory, no production-grade backups/SLA, and no free-hosted TensorFlow forecast. Upgrade the components that need persistence, uptime, or the deep-learning endpoint for real users.

## Environment variables

See [backend/.env.example](./backend/.env.example). Production requires `DATABASE_URL`, `TIFFIN_SECRET` (at least 32 bytes), and `CORS_ORIGINS`. `SEED_DEMO_DATA` defaults off in production. Keep `.env` files and all provider credentials out of Git.

## API overview

- `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/me`
- `GET /api/meals` (supports `search`, `category`, and `cook_id` filters)
- `POST /api/orders`, `PATCH /api/orders/{id}/status`
- `GET /api/meals/{id}/reviews`, `POST /api/reviews`
- Cook-owned menu: `POST /api/meals`, `PUT /api/meals/{id}`, `DELETE /api/meals/{id}`
- Role dashboards: `/api/student/dashboard`, `/api/cook/dashboard`, `/api/admin/dashboard`
- `GET /api/recommendations`, `GET /api/demand/prediction`

## Further hardening for real production use

Use paid, non-sleeping compute and managed Postgres with backups; enable the ML dependencies only on a service with adequate memory; add database migrations, monitoring, rate limiting, and automated backups; and review privacy, security, and account-recovery requirements before onboarding real students or cooks.
