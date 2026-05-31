import os
from flask import Blueprint, send_from_directory, abort, current_app

media_bp = Blueprint("media", __name__, url_prefix="/media")


@media_bp.get("/<path:filename>")
def serve_media(filename: str):
    workspace = current_app.config["WORKSPACE_DIR"]
    full_path = os.path.realpath(os.path.join(workspace, filename))
    if not full_path.startswith(os.path.realpath(workspace)):
        abort(403)
    directory = os.path.dirname(full_path)
    basename = os.path.basename(full_path)
    return send_from_directory(directory, basename)
