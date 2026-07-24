"""Test bootstrap.

Point the app at a throwaway copy of the demo database *before* ``app`` is
imported (settings resolve ``DATABASE_PATH`` at import time), so the test suite
never touches the shipped ``data/demo.db`` or any real database.
"""

import os
import shutil
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEMO_DB = _REPO_ROOT / "data" / "demo.db"

_TEST_DIR = tempfile.mkdtemp(prefix="nw-tracker-test-")
_TEST_DB = Path(_TEST_DIR) / "test.db"
shutil.copyfile(_DEMO_DB, _TEST_DB)

os.environ["DATABASE_PATH"] = str(_TEST_DB)
