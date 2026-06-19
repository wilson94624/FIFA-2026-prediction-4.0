from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DATA_DIR = ROOT_DIR / "frontend" / "src"
DATA_DIR = BACKEND_DIR / "data"
DATABASE_PATH = DATA_DIR / "predictor.db"


def load_env() -> None:
    """Load simple KEY=VALUE files without adding another runtime dependency."""
    for path in (ROOT_DIR / ".env", BACKEND_DIR / ".env"):
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{DATABASE_PATH.as_posix()}")
    world_cup_api_url: str = os.getenv("WORLD_CUP_API_URL", "https://worldcup26.ir/get/games")
    odds_api_key: str | None = os.getenv("THE_ODDS_API_KEY")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    odds_stale_minutes: int = int(os.getenv("ODDS_STALE_MINUTES", "30"))
    model_version: str = os.getenv("MODEL_VERSION", "4.0.0")
    default_seed: int = int(os.getenv("PREDICTION_SEED", "2026"))
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        if origin.strip()
    )


settings = Settings()
