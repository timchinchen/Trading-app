"""APScheduler wrapper: runs `run_once` every N minutes during US market hours."""

from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ...config import settings
from ..broker import AlpacaBroker
from .runner import run_once


class AgentScheduler:
    def __init__(self, broker: AlpacaBroker):
        self.broker = broker
        self.sched: Optional[AsyncIOScheduler] = None
        self._job = None

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
        self.sched.start()
        nr = self._job.next_run_time
        print(f"[agent] scheduler started; next run: {nr}")

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
        print(f"[agent] scheduler rescheduled every {cron_minutes}m; next: {self._job.next_run_time}")

    def shutdown(self) -> None:
        if self.sched:
            self.sched.shutdown(wait=False)
