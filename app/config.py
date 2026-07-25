import os
from pathlib import Path
from typing import ClassVar


class Settings:
    PROJECT_ROOT = Path(__file__).parent.parent
    _env_path = os.getenv("DATABASE_PATH")
    # Defaults to networa.db, which .gitignore excludes. It deliberately is NOT
    # demo.db: that file is committed to the repo, so making it the default would
    # mean the app's out-of-the-box database is the one file git tracks — one
    # `git add -A` away from publishing real finances. Tour the sample data with
    # `DB_NAME=demo.db python main.py`.
    DATABASE_PATH = (
        Path(_env_path)
        if _env_path
        else PROJECT_ROOT / "data" / os.getenv("DB_NAME", "networa.db")
    )
    # Seed a small illustrative portfolio when starting against an empty
    # database, so a fresh install has something on the dashboard. Never touches
    # a database that already holds assets. Set to 0 to start empty.
    SEED_SAMPLE_DATA = os.getenv("SEED_SAMPLE_DATA", "1") != "0"
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8000"))
    # Extra *hostnames* the app will answer to. Any IP address and localhost are
    # always accepted, so this is only needed when reaching the app by name —
    # typically behind a reverse proxy. Restricting names is what blocks DNS
    # rebinding (see app/security.py). "*" disables the check entirely.
    ALLOWED_HOSTS: ClassVar[list[str]] = [
        h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()
    ]


settings = Settings()
