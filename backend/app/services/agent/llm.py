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


ROLE_PREAMBLE = (
    "ROLE: You are a swing-trading assistant hunting quick wins over a 1-2 week "
    "holding horizon. You are NOT a low-latency/HFT bot and NOT a long-term "
    "investor. Your edge is synthesising every scrap of information supplied "
    "(tweets, fundamentals, market-intel snapshots, Stocktwits sentiment, news, "
    "SEC filings, price action) to predict near-term price moves on specific "
    "US-listed tickers. Favour catalysts that are likely to play out within "
    "5-10 trading days: earnings reactions, guidance revisions, product launches, "
    "insider flow, short squeezes, sector rotations, technical breakouts/breakdowns. "
    "Ignore decade-long theses and intraday scalps."
)


SYSTEM_PROMPT = (
    ROLE_PREAMBLE + "\n\n"
    "TASK: You are given a single tweet from a public investor. Extract any "
    "US-listed stock tickers the tweet references or implies, and rate the "
    "bullish/bearish sentiment of each from the perspective of a 1-2 week swing "
    "trade. Return STRICT JSON only, no markdown, no prose.\n\n"
    "Schema:\n"
    "{\n"
    "  \"tickers\": [ {\n"
    "    \"symbol\": \"AAPL\",\n"
    "    \"sentiment\": -1.0..1.0,   // negative = bearish, positive = bullish\n"
    "    \"confidence\": 0.0..1.0,\n"
    "    \"rationale\": \"one short sentence naming the near-term catalyst\"\n"
    "  } ],\n"
    "  \"meta\": { \"is_noise\": true|false }  // true if the tweet has no tradable 1-2 week signal\n"
    "}\n"
    "If the tweet has no ticker or no catalyst that can play out inside a 1-2 "
    "week window, return {\"tickers\": [], \"meta\": {\"is_noise\": true}}."
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
                ROLE_PREAMBLE + "\n\n"
                "Summarise the trading signals below from a 1-2 week swing-trade "
                "perspective in 3-5 short bullet points (ticker + catalyst + "
                "near-term bias). No preamble, no disclaimers.\n\n"
                "Then append a final line beginning 'Feedback:' listing in one "
                "sentence what extra data or signal would most improve your "
                "next run (e.g. options flow, sector ETF correlations, "
                "earnings-date calendar, pre-market quotes, analyst PT revisions)."
            ),
            user=text[:6000],
            temperature=0.2,
            timeout=120,
        )
        return out.strip()
    except Exception as e:
        return f"(summary unavailable: {e})"


ADVISOR_SYSTEM = (
    ROLE_PREAMBLE + "\n\n"
    "You are the portfolio advisor for a small personal paper-trading account "
    "(low-hundreds of dollars) running a 1-2 week swing strategy. Every hold/add/"
    "trim decision should be justified by a catalyst or technical setup that "
    "resolves within that window. You are given:\n"
    "  1. Current open positions with notional value, unrealised P/L, and age\n"
    "  2. Today's agent signals (symbol, score, confidence, mentions, rationale)\n"
    "  3. Trade proposals this run (executed, proposed, and skipped with reason)\n"
    "  4. Market intelligence snapshot (top movers, losers, headlines, sentiment)\n"
    "  5. Budget state (daily + weekly remaining, open-position count)\n\n"
    "Write a crisp, actionable recommendation in plain text (no markdown fences, "
    "no disclaimers) using EXACTLY these section headers:\n\n"
    "Portfolio Today\n"
    "- <SYMBOL>: hold | trim | add — catalyst / thesis playing out in next 1-2 weeks\n"
    "(one line per held position; write 'none' if flat)\n\n"
    "New Ideas (this run)\n"
    "- BUY <SYMBOL> ~$<notional> — near-term catalyst + why it beats alternatives\n"
    "(one line per executed or proposed new trade; write 'none' if nothing)\n\n"
    "Watchlist\n"
    "- <SYMBOL> — waiting on <trigger within 1-2 weeks>\n"
    "(2-4 names from signals that missed the bar this run)\n\n"
    "Risk notes\n"
    "- <one sentence about budget headroom / concentration / macro headlines / "
    "positions approaching the 2-week exit window>\n\n"
    "Feedback to operator\n"
    "- <one or two sentences describing the single most useful extra data feed, "
    "signal, or tuning change that would let you perform this role better on the "
    "next run — e.g. options flow, earnings calendar, analyst PT revisions, "
    "pre-market quotes, sector ETF correlations, higher LLM_CONCURRENCY, more "
    "watchlist depth, etc.>\n\n"
    "Stay under 250 words total. Refer to tickers in ALLCAPS. Never fabricate a "
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
