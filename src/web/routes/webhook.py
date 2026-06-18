import hashlib
import hmac
import logging
import os
import subprocess
import threading
from pathlib import Path

from flask import Blueprint, current_app, request

logger = logging.getLogger(__name__)

webhook = Blueprint("webhook", __name__, url_prefix="/webhook")


@webhook.post("/github")
def github_webhook():
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        logger.error("WEBHOOK_SECRET env var is not set")
        return {"error": "Webhook secret not configured"}, 500

    payload_bytes = request.get_data()
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    provided = sig_header[len("sha256="):] if sig_header.startswith("sha256=") else ""
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, provided):
        logger.warning("Invalid or missing X-Hub-Signature-256")
        return {"error": "Invalid signature"}, 403

    event = request.headers.get("X-GitHub-Event", "")

    if event == "ping":
        return {"message": "pong"}, 200

    if event != "push":
        return {"message": f"Event '{event}' ignored"}, 200

    try:
        ref = request.get_json(force=True)["ref"]
    except (TypeError, KeyError):
        return {"error": "Unexpected payload shape"}, 400

    if ref != "refs/heads/main":
        logger.info("Push to '%s' ignored", ref)
        return {"message": f"Push to '{ref}' ignored"}, 200

    project_root = current_app.config["PROJECT_ROOT"]
    logger.info("Push to main — scheduling git pull")

    def _pull():
        try:
            # Capture which files changed so we know what to rebuild
            before = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project_root, capture_output=True, text=True,
            ).stdout.strip()

            r = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode != 0:
                logger.error("git pull failed (rc=%d): %s %s", r.returncode, r.stdout, r.stderr)
                return

            logger.info("git pull succeeded: %s", r.stdout.strip())

            after = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project_root, capture_output=True, text=True,
            ).stdout.strip()

            changed = subprocess.run(
                ["git", "diff", "--name-only", before, after],
                cwd=project_root, capture_output=True, text=True,
            ).stdout.splitlines()

            sidecar_lock_changed = any(
                f.startswith("remotion-sidecar/package") for f in changed
            )
            sidecar_src_changed = any(
                f.startswith("remotion-sidecar/") for f in changed
            )

            if sidecar_lock_changed:
                _npm_install(project_root)

            if sidecar_src_changed or sidecar_lock_changed:
                _restart_sidecar()

            _reload_gunicorn(project_root)
        except Exception as exc:
            logger.exception("git pull error: %s", exc)

    def _npm_install(cwd: str):
        sidecar_dir = Path(cwd) / "remotion-sidecar"
        r = subprocess.run(
            ["npm", "install"],
            cwd=str(sidecar_dir),
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0:
            logger.info("npm install succeeded")
        else:
            logger.error("npm install failed: %s %s", r.stdout, r.stderr)

    def _restart_sidecar():
        uid = os.getuid()
        env = {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{uid}"}
        r = subprocess.run(
            ["systemctl", "--user", "restart", "remotion-sidecar"],
            capture_output=True, text=True, env=env,
        )
        if r.returncode == 0:
            logger.info("remotion-sidecar restarted")
        else:
            logger.error("remotion-sidecar restart failed: %s %s", r.stdout, r.stderr)

    def _reload_gunicorn(cwd: str):
        pid_file = Path(cwd) / "gunicorn.pid"
        if not pid_file.exists():
            logger.warning("gunicorn.pid not found at %s — skipping reload", pid_file)
            return
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, __import__("signal").SIGHUP)
            logger.info("Sent SIGHUP to gunicorn master (pid %d)", pid)
        except Exception as exc:
            logger.warning("Could not reload gunicorn: %s", exc)

    threading.Thread(target=_pull, daemon=True).start()
    return {"message": "Pull scheduled"}, 200
