import os
import ssl
from contextlib import asynccontextmanager

import certifi

# Point Python's default SSL context at certifi's CA bundle.
# Without this, macOS Python can't verify Alpaca / twscrape TLS and crashes
# with "SSL: CERTIFICATE_VERIFY_FAILED unable to get local issuer certificate".
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
# Monkey-patch the default SSL context so every async library that creates
# a context with no explicit bundle (alpaca-py's websockets, httpx, etc.)
# picks up certifi's CAs.
_orig_create_default_context = ssl.create_default_context


def _patched_default_context(*args, **kwargs):
    kwargs.setdefault("cafile", certifi.where())
    return _orig_create_default_context(*args, **kwargs)


ssl.create_default_context = _patched_default_context  # type: ignore[assignment]

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .deps import get_broker, get_market_data
from .routers import account, agent, auth, llm, orders, quotes, watchlist, ws
from .services.agent.scheduler import AgentScheduler

agent_scheduler: AgentScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_scheduler
    init_db()
    md = get_market_data()
    await md.start()
    print(f"[startup] APP_MODE={settings.APP_MODE}  MARKET_DATA_MODE={settings.MARKET_DATA_MODE}")
    if settings.AGENT_ENABLED:
        agent_scheduler = AgentScheduler(get_broker())
        agent_scheduler.start()
    yield
    if agent_scheduler:
        agent_scheduler.shutdown()


app = FastAPI(title="Personal Trading App", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.CORS_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "mode": settings.APP_MODE}


app.include_router(auth.router)
app.include_router(account.router)
app.include_router(orders.router)
app.include_router(quotes.router)
app.include_router(watchlist.router)
app.include_router(ws.router)
app.include_router(agent.router)
app.include_router(llm.router)
