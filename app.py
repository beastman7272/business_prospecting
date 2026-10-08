from dotenv import load_dotenv
load_dotenv()  # ← must be FIRST, before config import

import hmac

from flask import Flask, Response, request
from config import get_config
from models import db
from flask_migrate import Migrate
from blueprints.main import main_bp
from blueprints.api import api_bp


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config())

    db.init_app(app)
    Migrate(app, db)

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    @app.before_request
    def _password_gate():
        # Shared-password gate, active only when APP_PASSWORD is set (e.g. on
        # Railway). Any username is accepted; only the password is checked.
        expected = app.config.get("APP_PASSWORD")
        if not expected:
            return None
        auth = request.authorization
        supplied = (auth.password or "") if auth else ""
        if hmac.compare_digest(supplied.encode(), expected.encode()):
            return None
        return Response(
            "Password required.", 401,
            {"WWW-Authenticate": 'Basic realm="Business Prospecting"'},
        )

    @app.before_request
    def _bind_active_searcher():
        from flask import session
        from active_profile import set_active_searcher
        set_active_searcher(
            session.get("searcher") if app.config.get("SHOW_SEARCHER_PICKER") else None
        )

    @app.get("/healthz")
    def _healthz():
        return {"ok": True}

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=app.config.get("DEBUG", False))
