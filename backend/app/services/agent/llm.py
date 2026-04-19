"""LLM client for structured tweet analysis + portfolio advice.

Supports two providers, picked at call-time:
  - "ollama"  - local HTTP API at OLLAMA_HOST (default)
  - "openai"  - OpenAI-compatible chat completions API (works with OpenAI,
                Azure OpenAI, OpenRouter, etc. - point OPENAI_BASE_URL at it)

Callers pass the resolved provider/host/model/api_key from the settings_store
so that switching the provider in the UI takes effect on the next run without
restarting the server.
"""

import json
import re
from typing import Any

import httpx


# Provider value type.
Provider = str  # "ollama" | "openai"


SYSTEM_PROMPT = (
    "You are a disciplined equities trading assistant. You are given a tweet from "
    "a public investor. Extract any US-listed stock tickers the tweet references or "
    "implies, and rate the bullish/bearish sentiment of each. Return STRICT JSON only, "
    "no markdown, no prose.\n\n"
    "Schema:\n"
    "{\n"
    "  \"tickers\": [ {\n"
    "    \"symbol\": \"AAPL\",\n"
    "    \"sentiment\": -1.0..1.0,   // negative = bearish, positive = bullish\n"
    "    \"confidence\": 0.0..1.0,\n"
    "    \"rationale\": \"one short sentence\"\n"
    "  } ],\n"
    "  \"meta\": { \"is_noise\": true|false }  // true if the tweet has no tradable content\n"
    "}\n"
    "If the tweet has no ticker or tradable signal, return {\"tickers\": [], "
    "\"meta\": {\"is_noise\": true}}."
)


def _extract_json(s: str) -> dict[str, Any]:
    """LLMs sometimes wrap JSON. Grab the first {...} block."""
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if not m:
        return {"tickers": [], "meta": {"is_noise": True}}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"tickers": [], "meta": {"is_noise": True}}


async def _chat(
    *,
    provider: Provider,
    host: str,
    model: str,
    api_key: str,
    system: str,
    user: str,
    json_mode: bool = False,
    temperature: float = 0.2,
    timeout: float = 120.0,
) -> str:
    """Single chat call dispatched to the selected provider.

    Returns the raw assistant text (caller is responsible for JSON parsing if
    needed). Raises httpx.HTTPError on transport failures."""
    provider = (provider or "ollama").lower()
    if provider == "openai":
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is empty - configure it in Settings")
        url = f"{(host or 'https://api.openai.com/v1').rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""

    # Default: Ollama
    payload = {
        "model": model or "llama3.1:8b",
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{(host or 'http://localhost:11434').rstrip('/')}/api/chat",
            json=payload,
        )
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "") or ""


async def analyze_tweet(
    text: str,
    handle: str,
    host: str,
    model: str,
    *,
    provider: Provider = "ollama",
    api_key: str = "",
) -> dict[str, Any]:
    user_prompt = f"Tweet from @{handle}:\n\"\"\"\n{text[:4000]}\n\"\"\""
    try:
        content = await _chat(
            provider=provider,
            host=host,
            model=model,
            api_key=api_key,
            system=SYSTEM_PROMPT,
            user=user_prompt,
            json_mode=True,
            temperature=0.1,
            timeout=120,
        )
        return _extract_json(content)
    except Exception as e:
        print(f"[llm/{provider}] analyze_tweet error: {e}")
        return {"tickers": [], "meta": {"is_noise": True, "error": str(e)}}


async def summarize_run(
    text: str,
    host: str,
    model: str,
    *,
    provider: Provider = "ollama",
    api_key: str = "",
) -> str:
    try:
        out = await _chat(
            provider=provider,
            host=host,
            model=model,
            api_key=api_key,
            system=(
                "Summarise the trading signals below in 3-5 short bullet points. "
                "No preamble, no disclaimers."
            ),
            user=text[:6000],
            temperature=0.2,
            timeout=120,
        )
        return out.strip()
    except Exception as e:
        return f"(summary unavailable: {e})"


ADVISOR_SYSTEM = (
    "You are the portfolio advisor for a $200 personal paper-trading account. "
    "You are given:\n"
    "  1. Current open positions with notional value and unrealised P/L\n"
    "  2. Today's agent signals (symbol, score, confidence, mentions, rationale)\n"
    "  3. Trade proposals this run (executed, proposed, and skipped with reason)\n"
    "  4. Market intelligence snapshot (top movers, losers, headlines)\n"
    "  5. Budget state (daily + weekly remaining, open-position count)\n\n"
    "Write a crisp, actionable recommendation in plain text (no markdown fences, no "
    "disclaimers) using EXACTLY these section headers:\n\n"
    "Portfolio Today\n"
    "- <SYMBOL>: hold | trim | add — one-line reason\n"
    "(one line per held position; write 'none' if flat)\n\n"
    "New Ideas (this run)\n"
    "- BUY <SYMBOL> ~$<notional> — why this beats the alternatives\n"
    "(one line per executed or proposed new trade; write 'none' if nothing)\n\n"
    "Watchlist\n"
    "- <SYMBOL> — waiting on <condition>\n"
    "(2-4 names from signals that missed the bar this run, with a trigger)\n\n"
    "Risk notes\n"
    "- <one sentence about budget headroom / concentration / macro headlines>\n\n"
    "Stay under 200 words total. Refer to tickers in ALLCAPS. Never fabricate a "
    "symbol that is not in the input. If the input is thin, say so briefly in Risk "
    "notes."
)


async def advise_portfolio(
    context: str,
    host: str,
    model: str,
    *,
    provider: Provider = "ollama",
    api_key: str = "",
) -> str:
    """Produce a structured portfolio recommendation via the active LLM."""
    try:
        out = await _chat(
            provider=provider,
            host=host,
            model=model,
            api_key=api_key,
            system=ADVISOR_SYSTEM,
            user=context[:12000],
            temperature=0.2,
            timeout=180,
        )
        return out.strip()
    except Exception as e:
        return f"(advisor unavailable: {e})"
