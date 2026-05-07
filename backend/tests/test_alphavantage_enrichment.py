"""Unit tests for Alpha Vantage earnings enrichment helpers."""

import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.agent.intel import alpha_vantage as av


def test_parse_calendar_csv_groups_and_sorts_rows():
    csv_text = (
        "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
        "AAPL,Apple Inc,2026-07-30,2026-06-30,1.42,USD\n"
        "AAPL,Apple Inc,2026-04-30,2026-03-31,1.29,USD\n"
        "MSFT,Microsoft Corp,2026-08-01,2026-06-30,2.98,USD\n"
    )
    out = av._parse_calendar_csv(csv_text)
    assert set(out.keys()) == {"AAPL", "MSFT"}
    # Sorted by reportDate ascending.
    assert out["AAPL"][0]["reportDate"] == "2026-04-30"
    assert out["AAPL"][1]["reportDate"] == "2026-07-30"


def test_build_symbol_payload_includes_upcoming_and_previous_dates():
    today = date.today()
    prev_day = (today - timedelta(days=30)).isoformat()
    next_day = (today + timedelta(days=12)).isoformat()
    rows = [
        {
            "symbol": "AAPL",
            "name": "Apple Inc",
            "reportDate": prev_day,
            "fiscalDateEnding": "2026-03-31",
            "estimate": "1.29",
            "currency": "USD",
        },
        {
            "symbol": "AAPL",
            "name": "Apple Inc",
            "reportDate": next_day,
            "fiscalDateEnding": "2026-06-30",
            "estimate": "1.42",
            "currency": "USD",
        },
    ]
    payload = av._build_symbol_payload("AAPL", rows)
    assert payload["symbol"] == "AAPL"
    assert payload["company_name"] == "Apple Inc"
    assert payload["upcoming_report_date"] == next_day
    assert payload["last_report_date"] == prev_day
    assert payload["days_to_report"] == 12
    assert payload["estimate_eps"] == 1.42


def test_brief_line_formats_earnings_context():
    line = av.brief_line(
        {
            "upcoming_report_date": "2026-07-30",
            "days_to_report": 5,
            "estimate_eps": 1.42,
            "last_report_date": "2026-04-30",
        }
    )
    assert "next earnings 2026-07-30 (5d)" in line
    assert "est EPS 1.42" in line
    assert "last report 2026-04-30" in line


def test_fetch_many_uses_shared_calendar_rows(monkeypatch):
    async def _fake_rows(**kwargs):
        return (
            {
                "AAPL": [
                    {
                        "symbol": "AAPL",
                        "name": "Apple Inc",
                        "reportDate": (date.today() + timedelta(days=7)).isoformat(),
                        "fiscalDateEnding": "2026-06-30",
                        "estimate": "1.42",
                        "currency": "USD",
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(av, "_fetch_calendar_rows", _fake_rows)
    out = asyncio.run(
        av.fetch_many(
            ["AAPL", "TSLA"],
            api_key="demo",
        )
    )
    assert out["AAPL"]["upcoming_report_date"] is not None
    # TSLA was not in the fetched calendar, but payload still exists for consistency.
    assert out["TSLA"]["symbol"] == "TSLA"
    assert "upcoming_report_date" not in out["TSLA"]
