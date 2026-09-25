"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


class Config:
    API_BASE_URL = os.getenv(
        "API_BASE_URL", "http://localhost:3010/v1/chat/completions"
    )
    API_KEY = os.getenv("API_KEY", "")
    MODEL_NAME = os.getenv("MODEL_NAME", "auto")
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "600"))

    APP_NAME = os.getenv("APP_NAME", "Quotation AI Arena")
    APP_PORT = int(os.getenv("APP_PORT", "7860"))
    APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
    DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"

    DATABASE_PATH = _project_path(os.getenv("DATABASE_PATH", "data/chat_history.db"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = _project_path(os.getenv("LOG_FILE", "logs/app.log"))

    @classmethod
    def ensure_directories(cls) -> None:
        cls.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


config = Config()
config.ensure_directories()