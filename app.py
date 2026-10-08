from dotenv import load_dotenv
load_dotenv()  # ← must be FIRST, before config import

from flask import Flask
from config import DevConfig
from models import db
from flask_migrate import Migrate
from blueprints.main import main_bp
from blueprints.api import api_bp

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(DevConfig)

    db.init_app(app)
    Migrate(app, db)

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    @app.before_request
    def _bind_active_searcher():
        from flask import session
        from active_profile import set_active_searcher
        set_active_searcher(
            session.get("searcher") if app.config.get("SHOW_SEARCHER_PICKER") else None
        )

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
