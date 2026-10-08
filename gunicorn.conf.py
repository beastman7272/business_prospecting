"""Gunicorn settings, read automatically whenever gunicorn starts in this folder.

Keeps the hosted settings in the repo so they apply however the host invokes
gunicorn. Not used by local development (`python app.py`).
"""
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
threads = 4
# Contact discovery and dossier builds run inside the request and can take minutes.
timeout = 300


def on_starting(server):
    """Apply database migrations once, before workers start (production only)."""
    if os.getenv("APP_ENV", "").lower() not in ("production", "prod"):
        return
    from flask_migrate import upgrade
    from app import create_app

    app = create_app()
    with app.app_context():
        upgrade()
