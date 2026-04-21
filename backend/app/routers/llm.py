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
        if rs.llm_provider == "cohere":
            if not rs.cohere_api_key:
                return {"models": [], "error": "COHERE_API_KEY not set"}
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(
                    f"{rs.cohere_base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {rs.cohere_api_key}"},
                )
                r.raise_for_status()
                data = r.json()
                names = sorted({m.get("name") for m in data.get("models", []) if m.get("name")})
                return {"models": names}
        if rs.llm_provider == "huggingface":
            # Query the router's /v1/models endpoint (OpenAI-compatible) to
            # get models that are actually live on /v1/chat/completions.
            # Falls back to a curated verified-working list when the
            # router is unreachable or returns an empty set.
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        f"{rs.huggingface_base_url.rstrip('/')}/models",
                        headers={"Authorization": f"Bearer {rs.huggingface_api_key}"}
                        if rs.huggingface_api_key
                        else {},
                    )
                    r.raise_for_status()
                    data = r.json()
                    ids = sorted(
                        {
                            m.get("id")
                            for m in data.get("data", [])
                            if m.get("id")
                        }
                    )
                    if ids:
                        return {"models": ids}
            except Exception:
                pass
            return {
                "models": [
                    "meta-llama/Llama-3.1-8B-Instruct",
                    "meta-llama/Meta-Llama-3-8B-Instruct",
                    "meta-llama/Llama-3.3-70B-Instruct",
                    "Qwen/Qwen2.5-7B-Instruct",
                    "Qwen/Qwen3-8B",
                    "openai/gpt-oss-20b",
                ]
            }
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
    from ..services.agent.llm import _chat

    rs = get_runtime_settings()
    model = body.model or rs.llm_model
    system = body.system or DEFAULT_TRADING_SYSTEM
    # Flatten chat history into the user turn - the shared _chat dispatcher
    # takes a single system + user string so all four providers behave
    # identically.
    user_parts: list[str] = []
    for m in body.messages:
        role = m.role.upper() if m.role != "user" else "USER"
        user_parts.append(f"{role}: {m.content}")
    user_text = "\n\n".join(user_parts) if user_parts else ""
    t0 = time.time()
    try:
        content = await _chat(
            provider=rs.llm_provider,
            host=rs.llm_host,
            model=model,
            api_key=rs.llm_api_key,
            system=system,
            user=user_text,
            temperature=body.temperature,
            timeout=300,
        )
        content = (content or "").strip()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"LLM error ({rs.llm_provider}): {e}")
    dt = int((time.time() - t0) * 1000)
    return ChatOut(role="assistant", content=content, model=model, duration_ms=dt)
