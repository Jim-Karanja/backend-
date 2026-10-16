"""Settings come from the environment; backend/.env is loaded first (existing variables win)."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv is in requirements.txt; tolerate its absence in unit tests
        return
    load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    demo_mode: bool
    database_url: str
    author_salt: str
    fb_page_token: str
    x_bearer_token: str
    x_user_token: str
    openai_api_key: str
    openai_model: str
    frontend_origins: tuple


def get_settings() -> Settings:
    env = os.environ.get
    origins = tuple(o.strip().rstrip("/") for o in env("FRONTEND_ORIGINS", "").split(",") if o.strip())
    return Settings(
        demo_mode=env("HUB_DEMO_MODE", "true").strip().lower() not in ("0", "false", "no", "off"),
        database_url=env("DATABASE_URL", "").strip(),
        author_salt=env("AUTHOR_HASH_SALT", "").strip(),
        fb_page_token=env("FB_PAGE_TOKEN", "").strip(),
        x_bearer_token=env("X_BEARER_TOKEN", "").strip(),
        x_user_token=env("X_USER_TOKEN", "").strip(),
        openai_api_key=env("OPENAI_API_KEY", "").strip(),
        openai_model=env("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini",
        frontend_origins=origins or ("http://localhost:5173", "http://127.0.0.1:5173"),
    )
