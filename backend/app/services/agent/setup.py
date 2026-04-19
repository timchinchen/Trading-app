"""CLI helper to register a throwaway X account with twscrape.

Interactive (recommended - keeps passwords out of shell history/argv):
  .venv/bin/python -m app.services.agent.setup add

Cookies-based (bypass Cloudflare-blocked login - see README):
  .venv/bin/python -m app.services.agent.setup add_cookies

Non-interactive (ALWAYS wrap args in single quotes in zsh):
  .venv/bin/python -m app.services.agent.setup add 'user' 'pass' 'email' 'emailpass'
  .venv/bin/python -m app.services.agent.setup login
  .venv/bin/python -m app.services.agent.setup list
  .venv/bin/python -m app.services.agent.setup reset       # delete all accounts
"""

import asyncio
import getpass
import sqlite3
import sys

from ...config import settings


async def _add(user: str, pwd: str, email: str, emailpass: str):
    from twscrape import API
    api = API(settings.TWSCRAPE_DB)
    await api.pool.add_account(user, pwd, email, emailpass)
    print(f"[setup] added account {user}")


async def _login():
    from twscrape import API
    api = API(settings.TWSCRAPE_DB)
    await api.pool.login_all()
    print("[setup] logins attempted")


async def _list():
    from twscrape import API
    api = API(settings.TWSCRAPE_DB)
    accs = await api.pool.accounts_info()
    for a in accs:
        print(a)


def _prompt_add():
    print("Register a throwaway X account with twscrape.")
    print("(Passwords are read from a hidden prompt and never echoed.)")
    user = input("X username: ").strip()
    pwd = getpass.getpass("X password: ")
    email = input("Email address: ").strip()
    emailpass = getpass.getpass("Email password: ")
    if not (user and pwd and email and emailpass):
        print("[setup] all four fields are required")
        sys.exit(1)
    asyncio.run(_add(user, pwd, email, emailpass))


async def _add_cookies(user: str, pwd: str, email: str, emailpass: str, cookies: str):
    from twscrape import API
    api = API(settings.TWSCRAPE_DB)

    # Ensure DB + schema exist by asking twscrape to initialise.
    # accounts_info() triggers the migration/init path.
    try:
        await api.pool.accounts_info()
    except Exception:
        pass

    # Remove any prior row for this username so we can re-add cleanly.
    try:
        conn = sqlite3.connect(settings.TWSCRAPE_DB)
        conn.execute("DELETE FROM accounts WHERE username = ?", (user,))
        conn.commit()
        conn.close()
    except sqlite3.OperationalError:
        pass  # table not yet created

    await api.pool.add_account(user, pwd, email, emailpass, cookies=cookies)

    # With cookies, we skip login; mark the account active explicitly.
    try:
        await api.pool.set_active(user, True)
    except Exception:
        conn = sqlite3.connect(settings.TWSCRAPE_DB)
        try:
            conn.execute("UPDATE accounts SET active = 1 WHERE username = ?", (user,))
            conn.commit()
        finally:
            conn.close()
    print(f"[setup] added account {user} with cookies and marked active")


def _prompt_add_cookies():
    print("=== Add X account via browser session cookies ===")
    print()
    print("Steps:")
    print("  1. In a real browser, log in to https://x.com with your throwaway account.")
    print("     Solve any captcha, email code, or phone check.")
    print("  2. Open DevTools -> Application/Storage -> Cookies -> https://x.com")
    print("  3. Copy the value of the cookies 'auth_token' and 'ct0'.")
    print()
    user = input("X username (throwaway, no @): ").strip()
    pwd = getpass.getpass("X password (any - not used for login with cookies): ") or "unused"
    email = input("Email address: ").strip()
    emailpass = getpass.getpass("Email password (optional, ENTER to skip): ") or "unused"
    # Use visible input() here so you can verify the paste landed.
    auth_token = input("auth_token cookie value (will be shown - paste carefully): ").strip()
    ct0 = input("ct0 cookie value (will be shown - paste carefully): ").strip()
    if not (user and auth_token and ct0):
        print(f"[setup] got user={user!r} auth_token_len={len(auth_token)} ct0_len={len(ct0)}")
        print("[setup] username, auth_token, and ct0 are all required")
        sys.exit(1)
    print(f"[setup] ok: user={user} auth_token_len={len(auth_token)} ct0_len={len(ct0)}")
    cookies = f"auth_token={auth_token}; ct0={ct0}"
    asyncio.run(_add_cookies(user, pwd, email, emailpass, cookies))


def _reset():
    import os
    if os.path.exists(settings.TWSCRAPE_DB):
        os.remove(settings.TWSCRAPE_DB)
        print(f"[setup] removed {settings.TWSCRAPE_DB}")
    else:
        print(f"[setup] no existing db at {settings.TWSCRAPE_DB}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "add":
        if len(sys.argv) == 2:
            _prompt_add()
        elif len(sys.argv) == 6:
            asyncio.run(_add(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]))
        else:
            print(__doc__)
    elif cmd == "add_cookies":
        _prompt_add_cookies()
    elif cmd == "login":
        asyncio.run(_login())
    elif cmd == "list":
        asyncio.run(_list())
    elif cmd == "reset":
        _reset()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
