# TiffinConnect

TiffinConnect connects hostel students with local home cooks. It is a local full-stack demo with separate student, cook, and admin experiences, backed by FastAPI and SQLite.

## Features

- Student registration/login, meal search and dietary filters, portion and weekly/monthly ordering, order history, recommendations, and verified-order reviews.
- Cook menu management, stock tracking, order-status updates, sales summaries, and a seven-day demand forecast.
- Admin platform summary and recent-order overview. Admin accounts are seeded locally and cannot be created through public registration.
- LSTM demand forecasting and MLP-based meal recommendations run locally. The forecast is trained and evaluated with synthetic data; it is an academic demo, not operational demand advice.
- No paid services or API credentials are required. Seed meal photos use public Unsplash image URLs.

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Admin | `admin@tiffinconnect.com` | `admin123` |
| Student | `arjun@student.tiffin` | `student123` |
| Cook | `asha@cook.tiffin` | `cook123` |

Seed users and meals are created the first time the backend starts. The SQLite database and trained model artifacts are local files under `backend/`.

## Run locally (Windows PowerShell)

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
cd backend
..\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The API health check is at http://localhost:8000/api/health and interactive API docs are at http://localhost:8000/docs.

For frontend deployments where the API is not at `http://localhost:8000/api`, set `VITE_API_BASE_URL` to the API's `/api` base URL before building.

Set `TIFFIN_SECRET` to a private random value before using the app beyond a local demo. The built-in fallback key is intended only for local academic use.

## API overview

- `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/me`
- `GET /api/meals` (supports `search`, `category`, and `cook_id` filters)
- `POST /api/orders`, `PATCH /api/orders/{id}/status`
- `GET /api/meals/{id}/reviews`, `POST /api/reviews`
- `POST /api/meals`, `PUT /api/meals/{id}`, `DELETE /api/meals/{id}` (cook-owned menu)
- `GET /api/student/dashboard`, `/api/cook/dashboard`, `/api/admin/dashboard`
- `GET /api/recommendations`, `GET /api/demand/prediction`

## Notes

- SQLite, demo users, and generated ML artifacts are local and ignored by `backend/.gitignore`.
- The forecasting model uses an 80/20 chronological split of deterministic synthetic daily demand data. Its reported holdout MAE should not be interpreted as real-world accuracy.
- Password hashing uses bcrypt; the dependency range intentionally excludes bcrypt 5 because it is incompatible with the project's Passlib 1.7.4 integration.
