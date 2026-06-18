import os
from pathlib import Path
from datetime import datetime

from flask import Blueprint, render_template, send_from_directory, abort, current_app, request

output_bp = Blueprint("output", __name__, url_prefix="/output")


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _relative_time(dt: datetime) -> str:
    delta = datetime.now() - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    m = s // 60
    if m < 60:
        return f"{m}m ago"
    h = m // 60
    if h < 24:
        return f"{h}h ago"
    d = h // 24
    return f"{d}d ago"


@output_bp.get("/")
def index():
    output_dir = Path(current_app.config["OUTPUT_DIR"])
    entries = []
    for p in output_dir.iterdir():
        if p.suffix.lower() != ".mp4":
            continue
        stat = p.stat()
        entries.append({
            "name": p.name,
            "size": _human_size(stat.st_size),
            "mtime": datetime.fromtimestamp(stat.st_mtime),
            "mtime_rel": _relative_time(datetime.fromtimestamp(stat.st_mtime)),
        })
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return render_template("output_index.html", entries=entries)


@output_bp.get("/<path:filename>")
def serve_file(filename: str):
    output_dir = current_app.config["OUTPUT_DIR"]
    full_path = os.path.realpath(os.path.join(output_dir, filename))
    if not full_path.startswith(os.path.realpath(output_dir) + os.sep):
        abort(403)
    directory = os.path.dirname(full_path)
    basename = os.path.basename(full_path)
    dl = request.args.get("dl", "").strip()
    if dl:
        return send_from_directory(directory, basename, as_attachment=True, download_name=basename)
    return send_from_directory(directory, basename)
