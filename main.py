"""WSGI entry point for hosting (Railway's default start command is `gunicorn main:app`).

Local development still uses `python app.py`.
"""
from app import create_app

app = create_app()
