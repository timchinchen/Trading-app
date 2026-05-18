# X (Twitter) scraping with Playwright — full guide

This app’s agent pulls recent tweets with **Playwright** (headless Chromium) as the **primary** source. **twscrape** remains an optional **fallback** when Playwright fails (missing browser, crash, etc.).

Everything below is **backwards compatible**: if you do nothing new, behaviour stays **twscrape cookie injection** into Chromium exactly as before.

---

## Quick decision: which login method?

| Goal | What to configure |
|------|-------------------|
| Default / simplest | Leave `PLAYWRIGHT_STORAGE_STATE_PATH` empty. Put **`auth_token`** + **`ct0`** into **twscrape** via `add_cookies` (see below). |
| Same cookies, less brittle file handling | Still use twscrape — it is only a small SQLite store; Playwright reads it automatically. |
| Skip expanding cookies from twscrape | Set **`PLAYWRIGHT_STORAGE_STATE_PATH`** to a Playwright **`storage_state` JSON** file you generated after a real login (see [Option B](#option-b-playwright-storage_state-no-twscrape-cookie-expansion)). |
| Raspberry Pi / Docker ARM | Add **system Chromium** + **`PLAYWRIGHT_DISABLE_GPU=true`** (see [Raspberry Pi checklist](#raspberry-pi-and-docker-arm-checklist)). |

**Important:** If you set `PLAYWRIGHT_STORAGE_STATE_PATH` to a path that **does not exist**, the agent **errors immediately** (it does not silently fall back to twscrape cookies). Either create the file or clear the variable.

---

## Prerequisites

From the `backend` directory (virtualenv active):

```bash
cd backend
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
```

For **system Chromium** instead of Playwright’s bundled browser, install your OS package (e.g. `chromium` on Debian/Ubuntu/Raspberry Pi OS) and set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` (see [Environment variables](#environment-variables)).

---

## Option A — twscrape cookies (default)

### What gets stored

The CLI writes a row into **`TWSCRAPE_DB`** (default `./twscrape.db` next to `backend/.env`). Playwright reads **`auth_token`** and **`ct0`** from the **single active** account and injects them into the browser.

### Step 1 — Copy cookies from your browser

Use a **throwaway** X account dedicated to this app.

1. Log in at **https://x.com** (finish 2FA / email checks).
2. Open DevTools → **Application** (Chrome) or **Storage** (Firefox).
3. **Cookies** → `https://x.com`.
4. Copy the **Value** (full string) for:
   - **`auth_token`**
   - **`ct0`**

Copy only the value column — not the cookie name.

### Step 2 — Install cookies (interactive wizard)

```bash
cd backend
.venv/bin/python -m app.services.agent.setup add_cookies
```

You will be prompted for:

- X **username** (no `@`)
- Password / email fields — placeholders are fine when using cookies; they are stored for twscrape’s schema but **not** used for browser login here.
- **`auth_token`** and **`ct0`** paste values.

### Step 3 — Verify

```bash
.venv/bin/python -m app.services.agent.setup list
```

You should see one account marked usable. The scraper uses **`WHERE active = 1 LIMIT 1`**. If more than one row has `active = 1`, SQLite may pick an arbitrary row — **deactivate extras** in twscrape or keep only one active account.

### Step 4 — `.env`

```env
TWSCRAPE_DB=./twscrape.db
# Leave empty to use twscrape cookies (default).
PLAYWRIGHT_STORAGE_STATE_PATH=
```

### Docker / different paths

Point **`TWSCRAPE_DB`** at the **same path the container sees** (often a bind-mounted file). Run **`add_cookies` inside the container** or copy a populated `twscrape.db` from your workstation — **do not commit** real cookie databases.

---

## Option B — Playwright `storage_state` (no twscrape cookie expansion)

When **`PLAYWRIGHT_STORAGE_STATE_PATH`** points at an **existing JSON file**, Playwright loads that **`storage_state`** and **does not** inject cookies from twscrape.

Use this when you prefer logging in once in a **visible** browser and saving full session storage.

### Generate `storage_state` (recommended one-off script)

Run **on a machine that can open a graphical browser** (your laptop is ideal). Use the **same Playwright version** as `backend/requirements.txt` if possible.

Save the script below as **`backend/save_x_storage_state.py`** (any filename is fine if you adjust paths), then:

```bash
cd backend
.venv/bin/python save_x_storage_state.py
```

Example script:

```python
#!/usr/bin/env python3
"""One-shot: log into X manually, then save Playwright storage_state."""
import asyncio
from pathlib import Path

# Writes next to this script (e.g. backend/x-storage-state.json).
OUT = Path(__file__).resolve().parent / "x-storage-state.json"


async def main() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://x.com/login")
        print("Complete login in the browser window (2FA, captcha, etc.).")
        input(f"When your timeline loads, press ENTER here to save -> {OUT} ...")
        await context.storage_state(path=str(OUT))
        await browser.close()
    print(f"Saved: {OUT.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
```

Copy **`x-storage-state.json`** to your server (scp, vault, secrets mount). Point `.env` at it:

```env
PLAYWRIGHT_STORAGE_STATE_PATH=/absolute/path/to/x-storage-state.json
```

**Refreshing:** When X expires the session (symptoms below), repeat the script and overwrite the file.

### Relationship to twscrape when using `storage_state`

- Playwright **ignores** twscrape cookie rows for authentication **when** the storage file exists.
- The agent still passes **`TWSCRAPE_DB`** into Playwright for resolution logic; twscrape remains useful for **`twitter_client` fallback** if Playwright throws (install failure, etc.). Keeping **`add_cookies`** data in `twscrape.db` is recommended even if you primarily use `storage_state`.

---

## Environment variables

All variables live in **`backend/.env`** (see **`backend/.env.example`**).

| Variable | Default | Purpose |
|----------|---------|---------|
| `TWSCRAPE_DB` | `./twscrape.db` | SQLite DB used by twscrape CLI and cookie fallback path. |
| `PLAYWRIGHT_STORAGE_STATE_PATH` | *(empty)* | If set **and file exists**, use Playwright `storage_state`; skip twscrape cookie injection. |
| `PLAYWRIGHT_CHROMIUM_EXECUTABLE` | *(empty)* | If set, launch this Chromium instead of Playwright’s bundled binary (common on Pi). Example: `/usr/bin/chromium`. |
| `PLAYWRIGHT_DISABLE_GPU` | `false` | Append `--disable-gpu` at launch (often helps headless ARM). |
| `PLAYWRIGHT_USER_AGENT` | *(auto)* | Non-empty overrides default UA (Darwin vs Linux aarch64-style string). |
| `PLAYWRIGHT_RELAXED_FALLBACK` | `true` | If the **primary** Playwright session returns **zero tweets**, automatically runs a **second** session with longer waits, **`load`** navigation, and **no** image/font blocking. Set `false` to disable. |

---

## How the scraper behaves (primary + backup)

1. **Authentication:** `storage_state` **or** twscrape-expanded cookies (never both).
2. **Primary session:** Blocks images/fonts for speed; uses lighter navigation waits.
3. **Relaxed backup:** Runs **only if** `PLAYWRIGHT_RELAXED_FALLBACK=true`, primary returned **0 tweets**, and you were not already in relaxed mode. Intended for slow hardware or flaky X loads.

Logs label modes as `primary` vs `relaxed_backup`.

---

## Raspberry Pi and Docker ARM checklist

1. Install system Chromium (package name varies; often **`chromium`**).
2. In `.env`:

   ```env
   PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium
   PLAYWRIGHT_DISABLE_GPU=true
   PLAYWRIGHT_RELAXED_FALLBACK=true
   ```

3. Ensure **`AGENT_PER_ACCOUNT_TIMEOUT_S`** is not aggressively low — values under **30** are raised internally to **45** seconds, but Pi disks/network may still need the relaxed backup pass.

Broader Pi deployment (without local LLM) is in [`docs/RASPBERRY_PI_DEPLOYMENT.md`](RASPBERRY_PI_DEPLOYMENT.md).

---

## Troubleshooting

### Relative `TWSCRAPE_DB` / “wrong” `twscrape.db`

Every agent run prints **`TWSCRAPE_DB`** diagnostics: the raw `.env` value, **`process_cwd`** (Python's working directory), the **`absolute_path`** SQLite actually opens, **`file_exists`**, and optional **`WARNING`** if that path is missing but `backend/twscrape.db` exists (classic mis-start when cwd is not `backend/`). Playwright and twscrape fallback logs repeat **`path_arg`**, **`abspath`**, and **`cwd`** so you can confirm both layers agree.

### `CookiesMissingError` / “storage_state file not found”

- You set **`PLAYWRIGHT_STORAGE_STATE_PATH`** but the path is wrong or the file was not copied onto the server.
- **Fix:** Create/update the JSON or **unset** the variable to return to twscrape cookies.

### `no active account with cookies` / wizard errors

- **`TWSCRAPE_DB`** missing, empty, or no row with cookies.
- **Fix:** Run **`add_cookies`** again from `backend/` with fresh **`auth_token`** / **`ct0`**.

### Agent log shows tweets collected but UI says problems earlier / `0 tweets`

- Expired **`auth_token`** / **`ct0`** or **`storage_state`**.
- X bot-check (“Something went wrong”, captcha, unusual activity).
- **Fix:** Refresh cookies or regenerate **`storage_state`**. Enable **`PLAYWRIGHT_RELAXED_FALLBACK`** on slow hosts.

### Log probe shows `sign_in_link: true` or login wall text

Session is not authenticated in the browser context. Refresh secrets.

### Multiple active twscrape accounts

Only one **`active = 1`** row should win; duplicates cause **undefined** cookie choice. Use **`list`** / DB inspection and deactivate extras.

### Playwright installs but Chromium launch fails

- On minimal servers: install OS libraries for Chromium or point **`PLAYWRIGHT_CHROMIUM_EXECUTABLE`** at distro Chromium.
- **Fix:** Follow Playwright docs for your distro or use packaged **`chromium`**.

### twscrape fallback: pool exhausted / 15-minute lock

Backend logs may mention locks. Typical recovery:

```bash
cd backend
.venv/bin/twscrape --db ./twscrape.db reset_locks
```

Then refresh cookies with **`add_cookies`** if locks recur due to stale auth.

---

## Summary

- **Default:** **`add_cookies`** → **`TWSCRAPE_DB`** → Playwright injects **`auth_token`** + **`ct0`**.
- **Optional:** **`PLAYWRIGHT_STORAGE_STATE_PATH`** → skip injection; use saved **`storage_state`**.
- **Hardware:** **`PLAYWRIGHT_CHROMIUM_EXECUTABLE`** + **`PLAYWRIGHT_DISABLE_GPU`** + **`PLAYWRIGHT_RELAXED_FALLBACK`** for Pi / constrained environments.

For the short README excerpt (cookie names + wizard command), see [`README.md`](../README.md) § Agent setup.
