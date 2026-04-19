"""Ollama HTTP client for structured JSON analysis.

Default model is llama3.1:8b but qwen2.5:7b is also a good fit. The prompt
asks the model to return JSON only so we can reliably parse it.
"""

import json
import re
from typing import Any

import httpx


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
    """Ollama sometimes wraps JSON. Grab the first {...} block."""
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if not m:
        return {"tickers": [], "meta": {"is_noise": True}}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"tickers": [], "meta": {"is_noise": True}}


async def analyze_tweet(text: str, handle: str, host: str, model: str) -> dict[str, Any]:
    user_prompt = f"Tweet from @{handle}:\n\"\"\"\n{text[:4000]}\n\"\"\""
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            r = await client.post(
                f"{host.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "options": {"temperature": 0.1},
                },
            )
            r.raise_for_status()
            data = r.json()
            content = data.get("message", {}).get("content", "")
            return _extract_json(content)
        except Exception as e:
            print(f"[ollama] error: {e}")
            return {"tickers": [], "meta": {"is_noise": True, "error": str(e)}}


async def summarize_run(text: str, host: str, model: str) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            r = await client.post(
                f"{host.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content":
                         "Summarise the trading signals below in 3-5 short bullet points. "
                         "No preamble, no disclaimers."},
                        {"role": "user", "content": text[:6000]},
                    ],
                    "options": {"temperature": 0.2},
                },
            )
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "").strip()
        except Exception as e:
            return f"(summary unavailable: {e})"
