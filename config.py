import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = (
        os.getenv("DATABASE_URL")
        or f"sqlite:///{INSTANCE_DIR / 'prospecting.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

    # Provider keys. The app intentionally uses more than one provider:
    #   - OpenAI  : Stage 1 intel, and Stage 3 DossierLLM (dossier_llm_openai.py)
    #   - Gemini  : Stage 2 contact extraction (contact_discovery.GeminiExtractor)
    #   - Brave   : Stage 2/3 web search (contact_discovery.BraveSearchProvider)
    # A full Stage 2 -> Stage 3 run touches all three, so all are first-class here.
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY")


class DevConfig(BaseConfig):
    DEBUG = True
