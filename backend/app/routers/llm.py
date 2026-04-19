import time

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..schemas import ChatIn, ChatOut
from ..security import get_current_user
from ..services.settings_store import get_runtime_settings

router = APIRouter(prefix="/llm", tags=["llm"])


DEFAULT_TRADING_SYSTEM = (
    "You are a helpful assistant running locally for a personal trading app. "
    "You can discuss markets, stocks, trading psychology, and signals from the "
    "agent's scraped X accounts. Be concise and factual. You are not a licensed "
    "financial advisor; the user trades at their own risk."
)


@router.get("/info")
def info(_user=Depends(get_current_user)):
    rs = get_runtime_settings()
    return {
        "provider": rs.llm_provider,
        "host": rs.llm_host,
        "default_model": rs.llm_model,
    }


@router.get("/models")
async def list_models(_user=Depends(get_current_user)):
    rs = get_runtime_settings()
    try:
        if rs.llm_provider == "openai":
            if not rs.openai_api_key:
                return {"models": [], "error": "OPENAI_API_KEY not set"}
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(
                    f"{rs.openai_base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {rs.openai_api_key}"},
                )
                r.raise_for_status()
                data = r.json()
                ids = sorted({m.get("id") for m in data.get("data", []) if m.get("id")})
                return {"models": ids}
        # Ollama
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{rs.ollama_host.rstrip('/')}/api/tags")
            r.raise_for_status()
            data = r.json()
            return {"models": [m.get("name") for m in data.get("models", [])]}
    except Exception as e:
        return {"models": [], "error": str(e)}


@router.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn, _user=Depends(get_current_user)):
    rs = get_runtime_settings()
    model = body.model or rs.llm_model
    system = body.system or DEFAULT_TRADING_SYSTEM
    msgs = [{"role": "system", "content": system}] + [
        {"role": m.role, "content": m.content} for m in body.messages
    ]
    t0 = time.time()
    try:
        if rs.llm_provider == "openai":
            if not rs.openai_api_key:
                raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set; configure it in Settings")
            async with httpx.AsyncClient(timeout=300) as c:
                r = await c.post(
                    f"{rs.openai_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {rs.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": msgs,
                        "temperature": body.temperature,
                        "stream": False,
                    },
                )
                r.raise_for_status()
                data = r.json()
                content = ((data.get("choices") or [{}])[0].get("message", {}).get("content", "") or "").strip()
        else:
            async with httpx.AsyncClient(timeout=300) as c:
                r = await c.post(
                    f"{rs.ollama_host.rstrip('/')}/api/chat",
                    json={
                        "model": model,
                        "stream": False,
                        "messages": msgs,
                        "options": {"temperature": body.temperature},
                    },
                )
                r.raise_for_status()
                data = r.json()
                content = data.get("message", {}).get("content", "").strip()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"LLM error ({rs.llm_provider}): {e}")
    dt = int((time.time() - t0) * 1000)
    return ChatOut(role="assistant", content=content, model=model, duration_ms=dt)
