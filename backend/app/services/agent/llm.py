"""LLM client for structured tweet analysis + portfolio advice.

Supports four providers, picked at call-time:
  - "ollama"       - local HTTP API at OLLAMA_HOST (default)
  - "openai"       - OpenAI-compatible chat completions API (works with
                     OpenAI, Azure OpenAI, OpenRouter, etc. - point
                     OPENAI_BASE_URL at it)
  - "huggingface"  - Hugging Face Inference API (free serverless tier) via
                     the text-generation endpoint with an Instruct prompt
  - "cohere"       - Cohere chat API (free trial tier, ~1000 calls/month)

Callers pass the resolved provider/host/model/api_key from the settings_store
so that switching the provider in the UI takes effect on the next run without
restarting the server.
"""

import asyncio
import json
import re
from typing import Any

import httpx


# Provider value type.
Provider = str  # "ollama" | "openai" | "huggingface" | "cohere"


ROLE_PREAMBLE = (
    "ROLE: You are a swing-trading assistant hunting quick wins over a 1-2 week "
    "holding horizon (3-10 trading days). You are NOT a low-latency/HFT bot and "
    "NOT a long-term investor. Your edge is synthesising every scrap of "
    "information supplied (tweets, fundamentals, market-intel snapshots, "
    "Stocktwits sentiment, news, SEC filings, price action, moving averages, "
    "RSI, volume, gap behaviour) to predict near-term price moves on specific "
    "US-listed tickers.\n\n"
    "CORE PRINCIPLE: do not predict; execute repeatable setups with defined "
    "risk. Only act when trend, setup, and market conditions align.\n\n"
    "APPROVED SETUPS (one of these MUST be identifiable before a BUY):\n"
    "  1. TREND PULLBACK (primary) - price above 20 and 50-day MAs in a clear "
    "uptrend (higher highs, higher lows); pullback into support (10/20/50 MA "
    "or prior structure) on decreasing volume; entry on break of prior-day "
    "high or strong bullish reversal candle; stop below recent swing low or "
    "3-6% below entry; target 5-15% retest/continuation.\n"
    "  2. BREAKOUT FROM CONSOLIDATION - tight 5-15 day range, clear resistance, "
    "decreasing volatility, volume contraction -> expansion; entry on break "
    "above resistance with strong volume; stop inside the prior range or "
    "3-5% below entry; target 5-12%.\n"
    "  3. OVERSOLD BOUNCE (secondary, smaller size, exit fast if it fails) - "
    "RSI<30 or similar, 2-5 consecutive down days, approaching support; "
    "entry on first strong upward move or reclaim of key level; stop below "
    "recent low or 3-5% below entry; target 3-8%.\n"
    "  4. EARNINGS/NEWS MOMENTUM - gap up on earnings or news, high relative "
    "volume, holds key intraday levels; entry on break of high-of-day or "
    "next-day continuation; stop below gap support or 4-8% below entry; "
    "target 5-20%.\n\n"
    "MARKET FILTER (mandatory): only take BUYs when SPY is trending upward "
    "(price above its 50-day MA with 20-day MA rising). In choppy/bearish "
    "regimes downgrade every BUY to watch-only.\n\n"
    "STOCK SELECTION FILTER: high liquidity (tight spreads, strong volume), "
    "relative strength vs SPY, clean readable price structure.\n\n"
    "RISK RULES (hard): risk <=1% of total capital per trade; max 3-5 open "
    "positions; mandatory stop loss; never average down on losers; require "
    "risk/reward >= 1:2 before entry.\n\n"
    "TRADE MANAGEMENT: at +5% consider partial profit; at +8-10% move stop "
    "to breakeven; if no progress after 3-5 days exit; if stop hit exit "
    "immediately.\n\n"
    "ANTI-PATTERNS (reject): chasing extended moves, low-volume/illiquid "
    "stocks, ignoring overall market direction, overtrading/forcing setups, "
    "holding losing positions beyond stop.\n\n"
    "SUMMARY RULE: buy strength on weakness, buy breakouts on confirmation, "
    "cut losses quickly, only trade when market conditions support the setup."
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
    if provider == "huggingface":
        if not api_key:
            raise RuntimeError("HUGGINGFACE_API_KEY is empty - configure it in Settings")
        # HF retired the legacy api-inference.huggingface.co/models/{id}
        # endpoint in early 2026 and replaced it with an OpenAI-compatible
        # router at router.huggingface.co/v1. Existing users whose host
        # still points at the old base URL get auto-migrated here.
        base = (host or "https://router.huggingface.co/v1").rstrip("/")
        if "api-inference.huggingface.co" in base:
            base = "https://router.huggingface.co/v1"
        url = f"{base}/chat/completions"
        payload: dict[str, Any] = {
            "model": model or "mistralai/Mistral-7B-Instruct-v0.3",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            # One retry on 503 "model is loading" (cold starts).
            for attempt in range(2):
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 503 and attempt == 0:
                    await asyncio.sleep(3.0)
                    continue
                r.raise_for_status()
                break
            data = r.json()
            return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""

    if provider == "cohere":
        if not api_key:
            raise RuntimeError("COHERE_API_KEY is empty - configure it in Settings")
        base = (host or "https://api.cohere.com/v1").rstrip("/")
        url = f"{base}/chat"
        payload = {
            "model": model or "command-r-08-2024",
            "preamble": system,
            "message": user,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            # Cohere v1 /chat returns {"text": "..."} as the assistant
            # response. Some variants return chat_history with final entry.
            text = data.get("text")
            if text:
                return text
            hist = data.get("chat_history") or []
            if hist:
                return hist[-1].get("message", "") or ""
            return ""

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
    "(low-hundreds of dollars) running the 1-2 week swing strategy described "
    "above. Every BUY/HOLD/TRIM/ADD decision must map onto one of the four "
    "approved setups (trend pullback, breakout, oversold bounce, earnings/news "
    "momentum) with a concrete stop, target, and R/R >= 1:2. You are given:\n"
    "  1. Current open positions with notional, unrealised P/L, age\n"
    "  2. Today's agent signals (symbol, score, confidence, mentions, rationale)\n"
    "  3. Trade proposals this run (executed/proposed/skipped + reason)\n"
    "  4. Market intel + technical scan on every watchlist symbol (trend, MAs, "
    "RSI, setup classification, entry/stop/target)\n"
    "  5. Market regime check (SPY trend, go/no-go)\n"
    "  6. Budget state (daily + weekly remaining, open-position count)\n\n"
    "Write a crisp, actionable recommendation in plain text (no markdown, no "
    "disclaimers) using EXACTLY these section headers:\n\n"
    "Market Regime\n"
    "- <go | no-go> — one-line justification from the SPY trend snapshot\n\n"
    "Portfolio Today\n"
    "- <SYMBOL>: hold | trim | add | exit — setup it's playing out + stop + "
    "target; call out +5% partial-profit, +8% move-to-breakeven, or >=3-5 "
    "day time-stop triggers\n"
    "(one line per held position; write 'none' if flat)\n\n"
    "New Ideas (this run)\n"
    "- BUY <SYMBOL> ~$<notional> @ ~$<entry> stop $<stop> target $<target> "
    "(R/R ~<n>:1) — <setup name> + catalyst\n"
    "(one line per executed or proposed new trade; write 'none' if nothing "
    "or if regime = no-go)\n\n"
    "Watchlist\n"
    "- <SYMBOL> — waiting on <trigger within 1-2 weeks> (<setup name>)\n"
    "(2-5 names from watchlist/signals that missed the bar this run)\n\n"
    "Risk notes\n"
    "- <one sentence about budget headroom / concentration / macro headlines / "
    "positions approaching the 3-5 day time-stop>\n\n"
    "Feedback to operator\n"
    "- <one or two sentences naming the single most useful extra data feed, "
    "signal, or tuning change that would improve the next run - e.g. options "
    "flow, earnings calendar, sector ETF correlations, pre-market quotes, "
    "analyst PT revisions, deeper bar history, higher LLM_CONCURRENCY, more "
    "watchlist depth, etc.>\n\n"
    "Stay under 300 words. Refer to tickers in ALLCAPS. Never fabricate a "
    "symbol that is not in the input. Never propose a BUY when Market Regime "
    "is no-go. If the input is thin, say so briefly in Risk notes."
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
