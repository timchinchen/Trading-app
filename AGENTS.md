# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Personal Stocks Trading App (v1.2.1) — self-hosted swing-trading app with Paper/Live modes, backed by Alpaca.

- **Backend**: Python FastAPI on port 8000 (`backend/`)
- **Frontend**: React + Vite + TypeScript + Tailwind on port 5173 (`frontend/`)
- **Database**: SQLite (embedded, no external DB needed — auto-created as `trading.db`)

### Running services

**Backend** (from `backend/` directory):
```
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend** (from `frontend/` directory):
```
npm run dev
```

The Vite dev server proxies `/api` → `http://localhost:8000` and `/ws` → `ws://localhost:8000`, so the frontend talks to the backend through the proxy (no CORS issues in dev).

### Key gotchas

- **JWT_SECRET**: The backend refuses to start if `JWT_SECRET` is unset or still `"change_me"`. When creating `backend/.env` from `.env.example`, always generate a real secret: `openssl rand -hex 32`.
- **Alpaca API keys**: The app starts without them but market data, orders, and account info will fail. Paper keys are sufficient for development.
- **No ESLint config**: The frontend has no ESLint. TypeScript checking is via `npx tsc -b --noEmit` or the `npm run build` script which runs `tsc -b && vite build`.
- **Pre-existing test failures**: 4 tests in `backend/tests/test_alphavantage_enrichment.py` fail because they reference functions not yet implemented in the module. The remaining 65 tests pass.
- **Test runner**: `cd backend && .venv/bin/python -m pytest tests/ -v`
- **certifi**: Imported in `app/main.py` for SSL patch; installed as a transitive dep (not listed explicitly in `requirements.txt`).
- **Agent features** (Twitter scraping, LLM analysis) require additional setup (Playwright, Ollama/OpenAI keys, X cookies) and are optional for core app development.
