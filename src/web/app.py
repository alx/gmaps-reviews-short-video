import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask


def create_app(config: dict | None = None) -> Flask:
    load_dotenv()

    project_root = Path(__file__).parent.parent.parent
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32)
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    app.config["GOOGLE_MAPS_API_KEY"] = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    app.config["YOUTUBE_CLIENT_SECRETS"] = os.environ.get("YOUTUBE_CLIENT_SECRETS", "")
    app.config["GPHOTOS_CLIENT_SECRETS"] = os.environ.get("GPHOTOS_CLIENT_SECRETS", "")
    app.config["PROJECT_ROOT"] = str(project_root)

    workspace = project_root / "web_workspace"
    workspace.mkdir(exist_ok=True)
    app.config["WORKSPACE_DIR"] = str(workspace)

    if config:
        app.config.update(config)

    from .routes.wizard import wizard
    from .routes.media import media_bp
    from .routes.youtube_oauth import yt_oauth
    from .routes.gphotos_oauth import gp_oauth

    app.register_blueprint(wizard)
    app.register_blueprint(media_bp)
    app.register_blueprint(yt_oauth)
    app.register_blueprint(gp_oauth)

    return app


def run_dev() -> None:
    app = create_app()
    app.run(debug=True, host="127.0.0.1", port=5000, threaded=True)
