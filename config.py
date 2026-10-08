import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


def _database_url() -> str:
    """DATABASE_URL if set (e.g. Railway Postgres), else the local SQLite file.

    Railway/Heroku-style URLs use the "postgres://" scheme, which SQLAlchemy no
    longer accepts; normalize to the psycopg (v3) driver.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        return f"sqlite:///{INSTANCE_DIR / 'prospecting.db'}"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Drop dead pooled connections (managed Postgres closes idle ones).
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

    # Provider keys. The app intentionally uses more than one provider:
    #   - OpenAI  : Stage 1 intel, and Stage 3 DossierLLM (dossier_llm_openai.py)
    #   - Gemini  : Stage 2 contact extraction (contact_discovery.GeminiExtractor)
    #   - Brave   : Stage 2/3 web search (contact_discovery.BraveSearchProvider)
    # A full Stage 2 -> Stage 3 run touches all three, so all are first-class here.
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY")

    # Show the in-app "active searcher" picker. For multi-profile users
    # (e.g. a printer with several lens profiles). Off by default.
    SHOW_SEARCHER_PICKER = os.getenv("SHOW_SEARCHER_PICKER", "false").lower() in ("1", "true", "yes", "on")

    # Optional shared password gate (HTTP basic auth). Off unless set.
    APP_PASSWORD = os.getenv("APP_PASSWORD") or None


class DevConfig(BaseConfig):
    DEBUG = True


class ProdConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True


def get_config():
    """APP_ENV=production selects ProdConfig; anything else (default) is dev."""
    env = os.getenv("APP_ENV", "development").lower()
    if env in ("production", "prod"):
        if not os.getenv("SECRET_KEY"):
            raise RuntimeError("SECRET_KEY must be set when APP_ENV=production.")
        return ProdConfig
    return DevConfig
