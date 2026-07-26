"""Test bootstrap.

Point the app at a throwaway copy of the demo database *before* ``app`` is
imported (settings resolve ``DATABASE_PATH`` at import time), so the test suite
never touches the shipped ``data/demo.db`` or any real database.
"""

import asyncio
import os
import shutil
import tempfile
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEMO_DB = _REPO_ROOT / "data" / "demo.db"

_TEST_DIR = tempfile.mkdtemp(prefix="nw-tracker-test-")
_TEST_DB = Path(_TEST_DIR) / "test.db"
shutil.copyfile(_DEMO_DB, _TEST_DB)

os.environ["DATABASE_PATH"] = str(_TEST_DB)

# TestClient issues requests as Host: testserver. Addresses and localhost are
# always allowed, but "testserver" is a hostname, so it needs listing.
os.environ.setdefault("ALLOWED_HOSTS", "testserver")


@pytest.fixture
def on_fresh_db(tmp_path, monkeypatch) -> Callable:
    """Run ``body(db)`` against a newly created, schema-only database.

    The async services are driven through ``asyncio.run`` rather than
    pytest-asyncio, so each body must finish before its event loop goes away —
    hence the ``close_db()`` in the ``finally``, without which a later test
    would inherit an aiosqlite handle bound to a dead loop.
    """

    def run(body: Callable[[Any], Coroutine]):
        # Imported here, not at module scope: the environment above has to be in
        # place before ``app`` is first imported, and this file is what sets it.
        from app import database
        from app.config import settings

        monkeypatch.setattr(settings, "DATABASE_PATH", tmp_path / "fresh.db")
        monkeypatch.setattr(database, "_db", None)

        async def main():
            await database.init_db()
            try:
                return await body(await database.get_db())
            finally:
                await database.close_db()

        return asyncio.run(main())

    return run
