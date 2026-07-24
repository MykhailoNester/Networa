import os
from pathlib import Path


class Settings:
    PROJECT_ROOT = Path(__file__).parent.parent
    _env_path = os.getenv("DATABASE_PATH")
    DATABASE_PATH = (
        Path(_env_path)
        if _env_path
        else PROJECT_ROOT / "data" / os.getenv("DB_NAME", "demo.db")
    )
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8000"))


settings = Settings()
