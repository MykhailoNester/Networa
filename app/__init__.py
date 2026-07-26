from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .database import close_db, init_db
from .security import AllowedHostMiddleware, SameOriginMiddleware
from .services import currency_service
from .services.sample_data import maybe_seed_sample_data


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Startup
    await init_db()
    if settings.SEED_SAMPLE_DATA:
        created = await maybe_seed_sample_data()
        if created:
            # Printed, not logged: this is first-run guidance for someone who
            # just ran `python main.py`, and belongs next to uvicorn's banner.
            print(
                f"Seeded {created} sample assets into {settings.DATABASE_PATH.name} "
                "(every row is noted as sample data — delete them once you add "
                "your own, or start empty with SEED_SAMPLE_DATA=0)."
            )
    await currency_service.reload_display_state()
    _sync_display_globals()
    yield
    # Shutdown
    await close_db()


def _format_currency(value, currency: str = "USD", decimals: int = 0) -> str:
    symbol = currency_service.CURRENCY_SYMBOLS.get(
        (currency or "USD").upper(), (currency or "USD") + " "
    )
    fmt = f"{value:,.{decimals}f}"
    return f"{symbol}{fmt}"


def _format_display(value, decimals: int = 0) -> str:
    """Convert a USD value to the active display currency and format it."""
    if value is None:
        return "—"
    state = currency_service.display_state()
    converted = value * state["multiplier"]
    symbol = state["symbol"]
    fmt = f"{converted:,.{decimals}f}"
    return f"{symbol}{fmt}"


def create_app() -> FastAPI:
    app = FastAPI(title="Networa", version="0.1.0", lifespan=_lifespan)

    # Added inner-first: Starlette runs the last-added middleware outermost, so
    # the Host check happens before the origin check.
    app.add_middleware(SameOriginMiddleware)
    app.add_middleware(AllowedHostMiddleware)

    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

    from .routers import (
        assets,
        cashflows,
        dashboard,
        debts,
        exchange_rates,
        import_data,
        sheets,
        snapshots,
    )
    from .routers import settings as settings_router

    app.include_router(dashboard.router)
    app.include_router(assets.router)
    app.include_router(debts.router)
    app.include_router(sheets.router)
    app.include_router(cashflows.router)
    app.include_router(snapshots.router)
    app.include_router(import_data.router)
    app.include_router(exchange_rates.router)
    app.include_router(settings_router.router)

    return app


templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")
templates.env.filters["format_currency"] = _format_currency
templates.env.filters["format_display"] = _format_display

# Display currency globals — updated by _sync_display_globals()
templates.env.globals["display_currency"] = "USD"
templates.env.globals["display_symbol"] = "$"
templates.env.globals["display_multiplier"] = 1.0


def _sync_display_globals():
    """Copy the module-level display state into Jinja2 globals."""
    state = currency_service.display_state()
    templates.env.globals["display_currency"] = state["currency"]
    templates.env.globals["display_symbol"] = state["symbol"]
    templates.env.globals["display_multiplier"] = state["multiplier"]
