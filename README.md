# Personal Stocks Trading App — v1.2.1

Self-hosted swing-trading app with **Paper** and **Live** modes, backed by Alpaca. Runs entirely on your own hardware — no cloud subscriptions, no data sold.

- **Frontend:** React + Vite + TypeScript + Tailwind (cosmic-purple theme)
- **Backend:** FastAPI + SQLite + SQLAlchemy
- **Broker:** Alpaca (paper + live)
- **LLM:** Ollama (local) · OpenAI · Hugging Face (free tier) · Cohere (free tier)
- **Agent:** curated X/Twitter timelines → LLM sentiment → swing setups → auto-trade

---

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env       # fill in ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET
.venv/bin/uvicorn app.main:app --reload
```

API: `http://localhost:8000` — interactive docs at `/docs`

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

UI: `http://localhost:5173`

### 3. First run

1. Open the UI and register a local account (single-user app).
2. Add symbols to your watchlist (`AAPL`, `TSLA`, etc.). Pick **WS** (WebSocket, low-latency) or **Poll** (REST every N seconds) per symbol.
3. Place paper orders from the Symbol detail page.

### 4. Switching to Live mode

1. Stop the backend.
2. Edit `.env`: set `APP_MODE=live`, fill in `ALPACA_LIVE_KEY` / `ALPACA_LIVE_SECRET`.
3. Restart. The UI banner turns red and every order requires explicit confirmation.

---

## Feature overview

### Dashboard
- Account snapshot (cash, buying power, portfolio value)
- Open positions with live P/L and company name hover-tips
- Live watchlist with WebSocket / polling price feed, open price, prev close, % change
- **Trading Memory** card — compressed daily digest of agent activity with **Run now** and **Compress now** actions

### Symbol page
- Live tick chart (session history)
- Order ticket — Buy/Sell with auto-filled held quantity on Sell tab; "Sell all" shortcut
- Sell tab pre-fills with your current held shares (including fractional)

### Orders page
- Full order history with fill price, total cost, current price, % change since fill

### Agent page
- Run status, next scheduled run, per-ticker signals, executed trades, advisor recommendation
- **Run Now** button for immediate trigger
- Swing setup details (entry / stop / target / R:R)
- Auto-sell preview and manual trigger

### Chat
- Conversational LLM chat embedded in the app
- **Include context** checkbox — prepends your portfolio, open positions, agent settings, trading digests, and last 20 run summaries to every message so the LLM can answer trading-specific questions accurately
- Markdown rendering (bold, italic, numbered/bullet lists, inline code)
- Conversation persists across navigation (session storage)

### Settings
- Runtime-editable knobs — no restart required for most changes
- LLM provider selector (Ollama / OpenAI / Hugging Face / Cohere) with live key management
- Deep Analysis LLM (separate provider slot for advisor calls)
- All agent thresholds, budgets, and new v1.2 parameters editable in-browser

---

## Agent — how it works

The agent runs on a cron schedule (default every 30 minutes, Mon–Fri 09:00–15:59 ET).

```
every 30m (market hours)
  1. Fetch tweets — Playwright (headless Chromium) primary, twscrape fallback
  2. LLM analysis — extract tickers + sentiment + confidence per tweet
     → noise filtering: is_noise=true tweets excluded from signal counts
     → source weighting: AGENT_HANDLE_WEIGHTS applies per-handle multiplier [0.5–2.0]
  3. Aggregate signals — weighted score/confidence per ticker
     → intel boost: corroborated by stockanalysis.com movers / TradingView news
  4. Regime classification — SPY vs MA + slope → risk_on / neutral / risk_off
     → risk_off + AGENT_RISK_OFF_BLOCK_NEW_BUYS: skips new buys, exits still run
  5. Swing scanner — technical setups across watchlist (breakout, pullback, etc.)
     → regime-adaptive sizing: slot × AGENT_REGIME_*_MULT
  6. Adaptive exit engine (priority order per position):
     a. Hard stop        — plan stop_price hit
     b. Time stop        — position age > AGENT_MAX_HOLD_DAYS
     c. Momentum fade    — peak gain ≥ TRAIL_ARM_PCT then retraces TRAIL_RETRACE_PCT
     d. Partial TP       — gain ≥ PARTIAL_TAKE_PCT, sell PARTIAL_TAKE_FRACTION of position
  7. Static TP/SL sweep — AGENT_TAKE_PROFIT_PCT / AGENT_STOP_LOSS_PCT (legacy fallback)
  8. Daily loss cap      — FIFO realized P/L check; halts new trades if cap breached
  9. Execute / propose   — paper: auto-execute; live: propose-only (unless AUTO_EXECUTE_LIVE)
 10. Portfolio advisor   — Deep Analysis LLM produces structured recommendation
 11. Trading Digest      — events logged; compressed to daily summary at 09:30 ET
```

### One-time agent setup

**1. LLM (Ollama recommended for local privacy)**
```bash
brew install ollama
ollama serve
ollama pull llama3.1:8b
```

Alternatively configure OpenAI / Hugging Face / Cohere from the Settings page.

**2. Playwright + Chromium (Twitter scraping)**
```bash
cd backend
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
```

**3. X cookies** — create a throwaway X account, log in from a real browser, copy `auth_token` and `ct0` from DevTools:
```bash
cd backend
.venv/bin/python -m app.services.agent.setup add_cookies
.venv/bin/python -m app.services.agent.setup list
```

**4. Enable in `.env`**
```env
AGENT_ENABLED=true
AGENT_BUDGET_USD=200
AGENT_WEEKLY_BUDGET_USD=400
AGENT_MIN_POSITION_USD=20
AGENT_MAX_POSITION_USD=100
AGENT_DAILY_LOSS_CAP_USD=30
AGENT_MAX_OPEN_POSITIONS=6
AGENT_CRON_MINUTES=30
TWITTER_ACCOUNTS=blondesnmoney,PeterLBrandt,LindaRaschke,...

# LLM
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# v1.2 — swing knobs (sensible defaults, tune via Settings UI)
AGENT_MAX_HOLD_DAYS=8
AGENT_TRAIL_ARM_PCT=0.05
AGENT_TRAIL_RETRACE_PCT=0.35
AGENT_PARTIAL_TAKE_PCT=0.07
AGENT_PARTIAL_TAKE_FRACTION=0.5
AGENT_TAKE_PROFIT_PCT=0.07
AGENT_STOP_LOSS_PCT=0.05
AGENT_REGIME_RISK_ON_MULT=1.25
AGENT_REGIME_NEUTRAL_MULT=1.0
AGENT_REGIME_RISK_OFF_MULT=0.5
AGENT_RISK_OFF_BLOCK_NEW_BUYS=true
```

---

## v1.2 — What's new

### Source reliability weighting
Per-handle signal multiplier via `AGENT_HANDLE_WEIGHTS` (JSON, editable in Settings). Trusted traders get more influence; noise accounts less. Clipped to `[0.5, 2.0]`. Falls back to `1.0` on malformed JSON.

```json
{"PeterLBrandt": 1.25, "LindaRaschke": 1.2, "random_account": 0.7}
```

### Market-regime adaptive sizing
SPY is classified each run as `risk_on / neutral / risk_off` based on price vs MA and MA slope. Buy slot sizing is scaled by the matching multiplier. In `risk_off` with `AGENT_RISK_OFF_BLOCK_NEW_BUYS=true`, no new buys are issued — only exits and risk management proceed.

### Adaptive exit engine
Priority-ordered exit pass runs every agent cycle:
1. **Hard stop** — plan `stop_price` hit → full close
2. **Time stop** — position older than `AGENT_MAX_HOLD_DAYS` → full close
3. **Momentum fade** — peak gain ≥ `TRAIL_ARM_PCT`, current retraces ≥ `TRAIL_RETRACE_PCT` of peak → full close
4. **Partial TP** — gain ≥ `PARTIAL_TAKE_PCT` → sell `PARTIAL_TAKE_FRACTION`, flag prevents repeat

### Take-profit / Stop-loss fields (Settings UI)
Inputs now accept whole percent (`7` = 7%) so you can't accidentally enter 700%.

### Auto-sell from Symbol page
Sell tab pre-fills with your exact held quantity (including fractional shares). "Sell all (N)" shortcut resets to full position.

### Chat context injection
Checkbox in the Chat header prepends portfolio state, agent settings, trading digests, and last 20 run summaries to every LLM message.

### Company name hover-tips
Hover over any ticker on the Dashboard to see the full company/fund name, sourced from SEC EDGAR + a static ETF table.

### Robustness fixes (agent pipeline)
- Noise tweets (`is_noise=true`) properly excluded from signal aggregation
- Bearish reversal SELL proposals now carry actual held quantity (were `qty=0` before)
- Daily loss cap uses FIFO realized P/L matching, not a rough notional estimate

### Daily Trading Digest
Rolling log of agent events compressed daily at 09:30 ET by the Deep Analysis LLM. Last 3 digests prepended to advisor prompts as long-term memory. Visible on the Dashboard.

- **Run now** = run the daily compression now in normal mode (same behavior as the scheduler)
- **Compress now** = force regeneration now (bypasses normal daily guard)

---

## Safety rails

| Gate | What it does |
|------|-------------|
| `APP_MODE` | Resolved at boot — no in-app switch |
| Red banner | Persistent live-mode warning in UI |
| Confirmation dialog | Echoes mode on every manual order |
| `MANUAL_ORDER_MAX_NOTIONAL` | Server-side cap on any single order |
| `AGENT_BUDGET_USD` | Daily agent spend cap |
| `AGENT_WEEKLY_BUDGET_USD` | Rolling weekly spend cap |
| `AGENT_DAILY_LOSS_CAP_USD` | Halts new agent buys if realized P/L hits cap |
| `AGENT_MAX_OPEN_POSITIONS` | Position count ceiling |
| `AGENT_AUTO_EXECUTE_LIVE=false` | Live mode proposes only; you execute manually |
| `AGENT_RISK_OFF_BLOCK_NEW_BUYS` | Blocks all new buys when market regime is risk_off |
| `AGENT_MAX_HOLD_DAYS` | Force-closes stale positions on time-stop |
| `AGENT_STOP_LOSS_PCT` | Hard stop-loss on every position each run |
| WAL + FK | SQLite WAL mode + `foreign_keys=ON` on every connection |
| Daily DB backup | SQLite backup at 06:00 ET, 14-day rotation |

---

## Tuning profiles

### Aggressive (strong bull tape)
```
AGENT_REGIME_RISK_ON_MULT=1.5
AGENT_TRAIL_ARM_PCT=0.04
AGENT_TRAIL_RETRACE_PCT=0.40
AGENT_PARTIAL_TAKE_PCT=0.06
AGENT_MAX_HOLD_DAYS=6
AGENT_STOP_LOSS_PCT=0.04
```

### Default (profit-seeking, bounded)
```
AGENT_REGIME_RISK_ON_MULT=1.25
AGENT_REGIME_RISK_OFF_MULT=0.5
AGENT_TRAIL_ARM_PCT=0.05
AGENT_TRAIL_RETRACE_PCT=0.35
AGENT_PARTIAL_TAKE_PCT=0.07
AGENT_MAX_HOLD_DAYS=8
AGENT_STOP_LOSS_PCT=0.05
```

### Defensive (choppy / bear tape)
```
AGENT_REGIME_RISK_ON_MULT=1.0
AGENT_REGIME_RISK_OFF_MULT=0.3
AGENT_RISK_OFF_BLOCK_NEW_BUYS=true
AGENT_TRAIL_RETRACE_PCT=0.25
AGENT_MAX_HOLD_DAYS=5
AGENT_STOP_LOSS_PCT=0.03
```

---

## Project layout

```
trading-app/
├── backend/
│   ├── app/
│   │   ├── routers/          # FastAPI route handlers
│   │   ├── services/
│   │   │   ├── agent/        # runner, analyzer, allocator, swing_runner, exit engine
│   │   │   ├── company_names.py
│   │   │   ├── digest_store.py
│   │   │   └── market_data.py
│   │   ├── models.py         # SQLAlchemy ORM
│   │   ├── schemas.py        # Pydantic I/O models
│   │   └── config.py         # env + version
│   ├── tests/                # unit tests (pytest)
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── pages/            # Dashboard, Agent, Chat, Orders, Settings, Symbol
    │   ├── components/       # OrderTicket, Chart, Markdown, Nav, …
    │   └── api/              # hooks + types
    └── package.json
```

---

## Version history

| Version | Highlights |
|---------|-----------|
| **1.2.1** | Entry/exit defaults tightened for higher-quality swing trades (`AGENT_MIN_SCORE`, `AGENT_MIN_CONFIDENCE`, `AGENT_TOP_N_CANDIDATES`, tighter trailing/partial/time-stop defaults) |
| **1.2.0** | Source reliability weighting · regime-adaptive sizing · adaptive exit engine (time/momentum/partial TP) · take-profit/stop-loss whole-percent input · sell tab auto-fills held qty · Chat context injection · company name hover-tips · agent pipeline robustness fixes · Trading Digest |
| 1.0.8 | Symbol detail page error boundary + chart hardening |
| 1.0.7 | HF default model switched to Llama-3.1-8B-Instruct |
| 1.0.6 | Chat resets model on provider change + HF URL auto-migration |
| 1.0.5 | Chat empty-state shows active provider |
| 1.0.4 | Hugging Face OpenAI-compatible router |
| 1.0.3 | Hugging Face + Cohere LLM providers |
| 1.0.2 | Auto-sell (30-day max-hold window) |
| 1.0.1 | Prerequisites panel on login screen |

---

## Application screenshots

### Dashboard

![Dashboard](<docs/screenshots/TRADING-APP-Dashboard01.png>)

### Agent

![Agent UI 1](<docs/screenshots/TRADING-APP - Agent01.png>)
![Agent UI 2](docs/screenshots/agent-ui.png)

### Settings — LLM

![Settings LLM](<docs/screenshots/TRADING APP - Settings LLM.png>)

### Settings — Trading

![Settings Trading 1](<docs/screenshots/TRADING APP - Settings TRADING.png>)
![Settings Trading 2](<docs/screenshots/TRADING APP - Settings TRADING02.png>)
