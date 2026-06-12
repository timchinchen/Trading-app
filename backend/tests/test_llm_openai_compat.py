"""OpenAI Chat Completions compatibility tests."""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.agent import llm


def test_openai_payload_omits_temperature_for_reasoning_models():
    payload = llm._openai_chat_payload(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": "ping"}],
        temperature=0.2,
    )

    assert payload["model"] == "gpt-5-mini"
    assert "temperature" not in payload


def test_openai_payload_keeps_temperature_for_non_reasoning_models():
    payload = llm._openai_chat_payload(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "ping"}],
        temperature=0.2,
    )

    assert payload["temperature"] == 0.2


def test_openai_chat_gpt5_posts_without_temperature(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeClient)

    out = asyncio.run(
        llm._chat(
            provider="openai",
            host="https://api.openai.com/v1",
            model="gpt-5-mini",
            api_key="sk-test",
            system="system",
            user="hello",
            temperature=0.2,
        )
    )

    assert out == "ok"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert "temperature" not in captured["json"]
    assert "stream" not in captured["json"]


def test_openai_400_surfaces_response_body(monkeypatch):
    class FakeResponse:
        status_code = 400
        text = "unsupported temperature"

        def json(self):
            return {
                "error": {
                    "message": "Unsupported value: 'temperature' does not support 0.2",
                    "param": "temperature",
                }
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeClient)

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            llm._chat(
                provider="openai",
                host="https://api.openai.com/v1",
                model="gpt-4o-mini",
                api_key="sk-test",
                system="system",
                user="hello",
            )
        )

    assert "OpenAI API 400" in str(exc.value)
    assert "Unsupported value" in str(exc.value)
    assert "temperature" in str(exc.value)
