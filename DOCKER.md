# Docker deployment

Two containers:

| Service  | Image base                                      | Port (host) | Notes                                                |
|----------|-------------------------------------------------|-------------|------------------------------------------------------|
| backend  | `mcr.microsoft.com/playwright/python:v1.47.0`   | `8000`      | FastAPI + Uvicorn + Playwright/Chromium              |
| frontend | `cgr.dev/chainguard/node` (build) -> `cgr.dev/chainguard/nginx` | `5173`      | Static Vite bundle; browser hits backend at :8000 (served on container port 8080) |

Persistent data (sqlite + twscrape cookie db) lives in the named volume
`trading-app-data` and is mounted into the backend at `/data`.

Ollama is **not** bundled. Point the backend at a host instance:

```yaml
# docker-compose.override.yml
services:
  backend:
    environment:
      OLLAMA_HOST: http://host.docker.internal:11434   # Mac / Windows
      # OLLAMA_HOST: http://172.17.0.1:11434           # Linux (default bridge)
```

## 1. Quick start (local Mac)

```bash
cp backend/.env.example backend/.env
# fill in: ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET / JWT_SECRET
#         (optional) FMP_API_KEY, OPENAI_API_KEY, STOCKTWITS_COOKIES

docker compose up -d --build
open http://localhost:5173
```

Backend logs: `docker compose logs -f backend`

## 2. Deploying to a Linux host

The same `docker compose up -d --build` works on any amd64/arm64 Linux
box with Docker 24+ installed. A few host-specific overrides you'll
usually want:

```bash
# From your dev Mac, push prebuilt images for linux/amd64 (and arm64):
docker buildx bake -f docker-compose.yml \
  --set backend.platform=linux/amd64,linux/arm64 \
  --set frontend.platform=linux/amd64,linux/arm64 \
  --push
```

When the browser isn't on the same machine as Docker, override the
API + WS URLs at build time so the bundle knows where to call:

```bash
VITE_API_URL=http://trading.lan:8000 \
VITE_WS_URL=ws://trading.lan:8000 \
  docker compose up -d --build
```

## 3. Things worth knowing

- **First run is slow**: backend image is ~1.3 GB (Playwright + Chromium).
  Subsequent builds reuse the cached layers.
- **Twscrape login**: the agent expects X session cookies in the sqlite
  db. Run the one-shot setup inside the running backend container:
  ```bash
  docker compose exec backend python -m app.services.agent.setup add_cookies
  ```
- **Settings UI overrides .env**: any runtime setting you flip in
  Settings is written to the sqlite db in the volume, so it survives
  rebuilds. Resetting = stopping compose + `docker volume rm trading-app-data`.
- **Healthchecks**: both services ship `HEALTHCHECK` instructions; see
  `docker compose ps` for green/red status.
- **Playwright note**: the backend image already has Chromium installed
  for root. The Dockerfile runs `playwright install` again as insurance
  against base-image drift; it's a no-op on normal builds.

## 4. Common gotchas

| Symptom                                    | Fix                                                                 |
|--------------------------------------------|---------------------------------------------------------------------|
| Frontend loads but API calls 404           | `VITE_API_URL` build-arg is still `http://localhost:8000`; rebuild. |
| "CORS blocked" in browser console          | Set `CORS_ORIGIN` in `backend/.env` to the actual frontend URL.     |
| Backend can't reach Ollama on the host     | Use `host.docker.internal` (Mac/Win) or the bridge IP (Linux).      |
| `playwright not installed` errors in logs  | Your compose is using a stale image; `docker compose build --no-cache backend`. |
| Data gone after rebuild                    | Confirm the `trading-data` volume is mounted at `/data`.            |
