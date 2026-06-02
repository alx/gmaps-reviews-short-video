import datetime
import logging
import logging.handlers
import os
import subprocess
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from flask import Flask

GITHUB_REPO = "alx/gmaps-reviews-short-video"


def _read_commit_info(project_root: Path) -> tuple[str, str]:
    """Return (short_hash, human_date) for the current HEAD commit."""
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%H %ci"],
            cwd=str(project_root),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        full_hash, date_part = out.split(" ", 1)
        dt = datetime.datetime.strptime(date_part[:19], "%Y-%m-%d %H:%M:%S")
        return full_hash, dt.strftime("%-d %b %Y")
    except Exception:
        return "", ""


def _configure_logging(project_root: Path) -> None:
    log_file = os.environ.get("LOG_FILE") or str(project_root / "logs" / "app.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if os.environ.get("FLASK_DEBUG") else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def create_app(config: dict | None = None) -> Flask:
    load_dotenv()

    project_root = Path(__file__).parent.parent.parent
    _configure_logging(project_root)
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    app.config["GOOGLE_MAPS_API_KEY"] = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    app.config["GPHOTOS_CLIENT_SECRETS"] = os.environ.get("GPHOTOS_CLIENT_SECRETS", "")
    app.config["PROJECT_ROOT"] = str(project_root)

    yt_enabled = os.environ.get("YOUTUBE_PUBLISH_ENABLED", "").lower() in ("1", "true", "yes")
    app.config["YOUTUBE_PUBLISH_ENABLED"] = yt_enabled
    if yt_enabled:
        app.config["YOUTUBE_CLIENT_SECRETS"] = os.environ.get("YOUTUBE_CLIENT_SECRETS", "")

    workspace = project_root / "web_workspace"
    workspace.mkdir(exist_ok=True)
    app.config["WORKSPACE_DIR"] = str(workspace)

    app.jinja_env.filters["urlencode"] = quote_plus

    if config:
        app.config.update(config)

    commit_hash, commit_date = _read_commit_info(project_root)

    @app.context_processor
    def inject_flags():
        return {
            "yt_publish_enabled": app.config.get("YOUTUBE_PUBLISH_ENABLED", False),
            "commit_hash": commit_hash,
            "commit_short": commit_hash[:7] if commit_hash else "",
            "commit_date": commit_date,
            "github_commit_url": f"https://github.com/{GITHUB_REPO}/commit/{commit_hash}" if commit_hash else "",
        }

    from .routes.wizard import wizard
    from .routes.media import media_bp
    from .routes.gphotos_oauth import gp_oauth
    from .routes.webhook import webhook

    app.register_blueprint(wizard)
    app.register_blueprint(media_bp)
    app.register_blueprint(gp_oauth)
    app.register_blueprint(webhook)

    if yt_enabled:
        from .routes.youtube_oauth import yt_oauth
        app.register_blueprint(yt_oauth)

    return app


def run_dev() -> None:
    app = create_app()
    app.run(debug=True, host="127.0.0.1", port=5005, threaded=True)


def run_prod() -> None:
    from gunicorn.app.base import BaseApplication

    class _App(BaseApplication):
        def __init__(self, application, options):
            self.options = options
            self.application = application
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                self.cfg.set(key, value)

        def load(self):
            return self.application

    options = {
        "bind": "127.0.0.1:5005",
        "workers": 1,
        "worker_class": "gthread",
        "threads": 4,
        "loglevel": "info",
        "pidfile": str(Path(__file__).parent.parent.parent / "gunicorn.pid"),
    }
    _App(create_app(), options).run()
