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
from datetime import UTC, datetime

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

    The whole policy, pure and directly unit-testable: the local calendar date
    has advanced since the last run, and the clock has reached the configured
    hour. An empty ``last_run`` (never run) fires as soon as the hour is
    reached rather than waiting a full day, so turning the setting on at 09:00
    runs promptly instead of waiting for tomorrow. This also gives free
    catch-up after downtime: a container that was off overnight runs on the
    next boot, which is what a self-hosted tracker wants, and needs no
    wall-clock arithmetic that DST could break.
    """
    return now.date().isoformat() != last_run and now.hour >= run_hour


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
