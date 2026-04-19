import time

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..schemas import ChatIn, ChatOut
from ..security import get_current_user

router = APIRouter(prefix="/llm", tags=["llm"])


DEFAULT_TRADING_SYSTEM = (
    "You are a helpful assistant running locally for a personal trading app. "
    "You can discuss markets, stocks, trading psychology, and signals from the "
    "agent's scraped X accounts. Be concise and factual. You are not a licensed "
    "financial advisor; the user trades at their own risk."
)


@router.get("/info")
def info(_user=Depends(get_current_user)):
    return {
        "host": settings.OLLAMA_HOST,
        "default_model": settings.OLLAMA_MODEL,
    }


@router.get("/models")
async def list_models(_user=Depends(get_current_user)):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{settings.OLLAMA_HOST.rstrip('/')}/api/tags")
            r.raise_for_status()
            data = r.json()
            return {"models": [m.get("name") for m in data.get("models", [])]}
    except Exception as e:
        return {"models": [], "error": str(e)}


@router.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn, _user=Depends(get_current_user)):
    model = body.model or settings.OLLAMA_MODEL
    system = body.system or DEFAULT_TRADING_SYSTEM
    messages = [{"role": "system", "content": system}] + [
        {"role": m.role, "content": m.content} for m in body.messages
    ]
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(
                f"{settings.OLLAMA_HOST.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "messages": messages,
                    "options": {"temperature": body.temperature},
                },
            )
            r.raise_for_status()
            data = r.json()
            content = data.get("message", {}).get("content", "").strip()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")
    dt = int((time.time() - t0) * 1000)
    return ChatOut(role="assistant", content=content, model=model, duration_ms=dt)
