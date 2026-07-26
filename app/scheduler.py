"""Opt-in daily valuation loop.

A plain ``asyncio`` task, not APScheduler: one fixed daily job needs no cron
parser, no job store, and no second event-loop lifecycle to manage alongside
uvicorn's. The loop is started from the app lifespan only when
``settings.auto_valuation_enabled`` is ``"1"`` (see ``app/__init__.py``), so a
default boot starts no background task at all — the strongest guarantee that
the test suite never grows one by accident.

This module holds no money math, only the timer and the settings plumbing —
that is also why it lives beside ``security.py`` as app-lifecycle code rather
than under ``app/services/``.
"""

import asyncio
import contextlib
from datetime import UTC, date, datetime, timedelta

from .services import currency_service, settings_service, snapshot_service

SETTING_ENABLED = "auto_valuation_enabled"  # "1" | "0", default "0"
SETTING_RUN_HOUR = "auto_valuation_run_hour"  # "0".."23", default "3"
SETTING_LAST_RUN = "auto_valuation_last_run"  # "YYYY-MM-DD", default ""
DEFAULT_RUN_HOUR = 3
TICK_SECONDS = 900  # 15 minutes between checks

_task: asyncio.Task[None] | None = None


def parse_run_hour(raw: str) -> int:
    """Parse a settings-stored run hour, falling back to DEFAULT_RUN_HOUR for
    anything unparseable or out of the 0-23 range."""
    try:
        hour = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_RUN_HOUR
    return hour if 0 <= hour <= 23 else DEFAULT_RUN_HOUR


def should_run(last_run: str, now: datetime, run_hour: int) -> bool:
    """Whether the daily job should fire right now.

    Pure and directly unit-testable. Four cases, checked in order:

    - ``last_run`` is empty or not a parseable date (never run before) ->
      run now.
    - ``last_run`` is today -> already ran today, regardless of the hour ->
      do not run.
    - ``last_run`` is strictly earlier than yesterday -> at least one whole
      day was missed while the app was off -> run *immediately*, whatever the
      current hour, as a catch-up. Without this, ``run_hour=15`` and a 09:00
      boot after three days offline would wait until 15:00 to notice, and an
      app only ever up between 00:00 and its ``run_hour`` would never run at
      all.
    - ``last_run`` is yesterday -> the normal daily cadence: wait until the
      clock reaches ``run_hour``.

    A caught-up run still reprices everything as of *today* —
    ``market_service.fetch_ticker_price`` returns a current quote, not a
    historical one, so the missed days themselves are never backfilled. This
    only guarantees the marker (and so the numbers) is never more than one
    calendar day stale.
    """
    today = now.date()
    try:
        last_run_date = date.fromisoformat(last_run)
    except ValueError:
        return True  # never run before, or an unparseable marker
    if last_run_date >= today:
        return False  # already ran today
    if last_run_date < today - timedelta(days=1):
        return True  # missed at least one whole day: catch up now
    return now.hour >= run_hour  # last run was yesterday: normal cadence


def next_run_at(last_run: str, now: datetime, run_hour: int) -> datetime:
    """The wall-clock time the loop is next expected to fire, given the same
    inputs ``should_run`` would see right now.

    Display-only, for the Settings page — the loop itself only ever consults
    ``should_run``; this never gates a run. Re-derives the same date
    comparison ``should_run`` makes rather than inferring it from ``now.hour``:
    a catch-up run can stamp ``last_run`` as today at any hour, including one
    earlier than ``run_hour``, so "is today's hour still ahead of us" is not a
    reliable stand-in for "did it already run today".
    """
    if should_run(last_run, now, run_hour):
        return now  # a tick within TICK_SECONDS catches this
    today_at_hour = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    last_run_date = date.fromisoformat(last_run)  # should_run already validated this
    if last_run_date >= now.date():
        return today_at_hour + timedelta(days=1)  # already ran today: wait for tomorrow
    return today_at_hour  # ran yesterday; today's hour has not arrived yet


async def is_enabled() -> bool:
    return await settings_service.get_setting(SETTING_ENABLED, "0") == "1"


def is_running() -> bool:
    return _task is not None and not _task.done()


async def run_once(price_date: str | None = None) -> dict:
    """Run the daily valuation once and refresh the Jinja display globals.

    ``_sync_display_globals`` is imported lazily, inside the function, rather
    than at module scope: ``app/scheduler.py`` is imported by
    ``app/__init__.py`` while that module is still executing (see the lifespan
    wiring there), so a module-level import back into it here would be a
    circular, partial-initialization import. ``app/routers/settings.py``
    reaches the same function the same lazy way.
    """
    report = await snapshot_service.run_daily_valuation(price_date)
    await currency_service.reload_display_state()
    from . import _sync_display_globals

    _sync_display_globals()
    # Printed, not logged: the same "small self-hosted app, no log aggregator
    # to hand this to" precedent as the first-run seeding message in
    # app/__init__.py.
    print(
        f"[auto-valuation] {report['price_date']}: {report['updated']} updated, "
        f"{report['failed']} failed, {report['skipped']} skipped, "
        f"{report['reconverted']} fx-reconverted"
    )
    return report


async def _loop() -> None:
    while True:
        # Re-read the setting every tick — a self-healing check, so a task
        # left running from before the setting was turned off cannot keep
        # doing work.
        if await is_enabled():
            now = datetime.now(tz=UTC).astimezone()
            last_run = await settings_service.get_setting(SETTING_LAST_RUN, "")
            run_hour = parse_run_hour(
                await settings_service.get_setting(SETTING_RUN_HOUR, "")
            )
            if should_run(last_run, now, run_hour):
                try:
                    await run_once()
                except Exception as exc:  # noqa: BLE001 - a failed run must not kill the loop
                    print(f"[auto-valuation] run failed: {type(exc).__name__}: {exc}")
                # Advanced whether the run succeeded or failed, so a
                # persistently failing upstream (Yahoo or NBU down) is retried
                # once a day, not on every 15-minute tick.
                await settings_service.set_setting(
                    SETTING_LAST_RUN, now.date().isoformat()
                )
        await asyncio.sleep(TICK_SECONDS)


async def start() -> bool:
    """Start the daily loop if it is not already running.

    Idempotent: calling this while the loop is already running is a no-op.
    Returns whether a task is running after the call.
    """
    global _task
    if not is_running():
        _task = asyncio.create_task(_loop())
    return is_running()


async def stop() -> None:
    """Cancel the loop and wait for it to finish. A no-op when not running."""
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
