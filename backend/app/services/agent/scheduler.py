"""APScheduler wrapper: runs `run_once` every N minutes during US market hours.

Also owns the daily Trading Digest compression job, which fires once per
weekday at 09:30 US/Eastern (market open) and rolls the last 7 days of
DigestEntry rows into a DailyDigest via the Deep Analysis LLM.
"""

import asyncio
import os
import shutil
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ...config import settings
from ...db import engine
from ..broker import AlpacaBroker
from ..digest_store import compress_daily
from .runner import run_once


# How many daily SQLite backups we keep before rotating the oldest out.
_DB_BACKUP_KEEP_DAYS = 14


class AgentScheduler:
    def __init__(self, broker: AlpacaBroker):
        self.broker = broker
        self.sched: Optional[AsyncIOScheduler] = None
        self._job = None
        self._digest_job = None
        self._backup_job = None

    def _schedule_digest_job(self) -> None:
        """Attach the daily digest compression to the scheduler (09:30 ET).

        Note: Job.next_run_time is only populated *after* the scheduler has
        been started, so we defensively getattr() it for the log line - the
        job itself is valid either way."""
        if self.sched is None:
            return
        digest_trigger = CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=30,
            timezone="America/New_York",
        )
        if self._digest_job:
            self._digest_job.reschedule(trigger=digest_trigger)
        else:
            self._digest_job = self.sched.add_job(
                self._digest, trigger=digest_trigger, id="trading_digest_daily"
            )
        nr = getattr(self._digest_job, "next_run_time", None)
        print(f"[digest] daily compression job armed; next: {nr or '(pending scheduler start)'}")

    async def _digest(self):
        try:
            await compress_daily()
        except Exception as e:
            print(f"[digest] compress_daily crashed: {e}")

    def _schedule_backup_job(self) -> None:
        """Snapshot the sqlite DB once per weekday at 06:00 ET.

        SQLite + WAL is resilient but not invincible - a crash during a
        write, or accidental `rm trading.db`, is irreversible without a
        backup. We copy the file to a rotating `./backups/` folder using
        SQLite's `.backup` command via shutil (works while the db is open).
        Non-sqlite backends (e.g. future Postgres) skip cleanly.
        """
        if self.sched is None:
            return
        backup_trigger = CronTrigger(
            day_of_week="mon-fri",
            hour=6,
            minute=0,
            timezone="America/New_York",
        )
        if self._backup_job:
            self._backup_job.reschedule(trigger=backup_trigger)
        else:
            self._backup_job = self.sched.add_job(
                self._backup_db, trigger=backup_trigger, id="db_backup_daily"
            )
        nr = getattr(self._backup_job, "next_run_time", None)
        print(f"[backup] daily db-backup job armed; next: {nr or '(pending scheduler start)'}")

    async def _backup_db(self):
        try:
            await asyncio.to_thread(_do_db_backup)
        except Exception as e:
            print(f"[backup] db backup crashed: {e}")

    def start(self) -> None:
        if not settings.AGENT_ENABLED:
            print("[agent] disabled via AGENT_ENABLED=false")
            return
        self.sched = AsyncIOScheduler(timezone="America/New_York")
        minute_expr = f"*/{max(1, settings.AGENT_CRON_MINUTES)}"
        trigger = CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute=minute_expr,
            timezone="America/New_York",
        )
        self._job = self.sched.add_job(self._runner, trigger=trigger, id="agent_main")
        # Start the scheduler BEFORE attaching secondary jobs so their
        # next_run_time is populated when we log it. APScheduler leaves
        # next_run_time as the attribute-missing sentinel until the sched
        # is running, which used to crash startup on the debug print.
        self.sched.start()
        self._schedule_digest_job()
        self._schedule_backup_job()
        nr = getattr(self._job, "next_run_time", None)
        print(f"[agent] scheduler started; next run: {nr or '(pending)'}")

    async def _runner(self):
        try:
            await run_once(self.broker)
        except Exception as e:
            print(f"[agent] run_once crashed: {e}")

    def next_run_at(self) -> Optional[datetime]:
        if self._job is None:
            return None
        return self._job.next_run_time

    def reschedule(self, cron_minutes: int, *, enabled: bool = True) -> None:
        """Apply a new cron interval (or fully start/stop) at runtime.

        Called from the Settings UI when AGENT_ENABLED or AGENT_CRON_MINUTES
        is changed via the /agent/settings endpoint."""
        if not enabled:
            self.shutdown()
            self.sched = None
            self._job = None
            print("[agent] scheduler disabled via runtime setting")
            return
        if self.sched is None:
            self.sched = AsyncIOScheduler(timezone="America/New_York")
            self.sched.start()
        minute_expr = f"*/{max(1, int(cron_minutes))}"
        trigger = CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute=minute_expr,
            timezone="America/New_York",
        )
        if self._job:
            self._job.reschedule(trigger=trigger)
        else:
            self._job = self.sched.add_job(self._runner, trigger=trigger, id="agent_main")
        # Make sure the digest + backup jobs are still attached (in case the
        # scheduler was just recreated from a disabled state).
        self._schedule_digest_job()
        self._schedule_backup_job()
        nr = getattr(self._job, "next_run_time", None)
        print(f"[agent] scheduler rescheduled every {cron_minutes}m; next: {nr or '(pending)'}")

    def next_digest_at(self) -> Optional[datetime]:
        if self._digest_job is None:
            return None
        return self._digest_job.next_run_time

    def shutdown(self) -> None:
        if self.sched:
            self.sched.shutdown(wait=False)


def _do_db_backup() -> None:
    """Sync helper - runs in a worker thread so we never block the loop."""
    if not engine.url.get_backend_name().startswith("sqlite"):
        return  # non-sqlite backends handle their own backups

    db_path = engine.url.database
    if not db_path or not os.path.isfile(db_path):
        print(f"[backup] db file not found at {db_path!r}; skipping")
        return

    backup_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)) or ".", "backups")
    os.makedirs(backup_dir, exist_ok=True)

    stamp = datetime.utcnow().strftime("%Y%m%d")
    dest = os.path.join(backup_dir, f"trading-{stamp}.db")

    # Use sqlite3's online backup API to avoid copying a half-written page.
    # Falls back to shutil.copy if anything goes wrong - still better than
    # nothing.
    try:
        import sqlite3

        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)
        finally:
            src.close()
            dst.close()
        print(f"[backup] sqlite backup -> {dest}")
    except Exception as e:
        print(f"[backup] sqlite backup api failed ({e}); falling back to file copy")
        try:
            shutil.copy2(db_path, dest)
            print(f"[backup] file copy -> {dest}")
        except Exception as e2:
            print(f"[backup] file copy also failed: {e2}")
            return

    # Rotate: keep the newest _DB_BACKUP_KEEP_DAYS files, delete the rest.
    try:
        files = sorted(
            (f for f in os.listdir(backup_dir) if f.startswith("trading-") and f.endswith(".db")),
            reverse=True,
        )
        for old in files[_DB_BACKUP_KEEP_DAYS:]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except Exception:
                pass
    except Exception as e:
        print(f"[backup] rotation failed: {e}")
