import json
import os
import time
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    stream_with_context,
    url_for,
)

from .. import tasks as task_mod
from ..tasks import TaskStatus

wizard = Blueprint("wizard", __name__)


def _workspace() -> str:
    return current_app.config["WORKSPACE_DIR"]


def _api_key() -> str:
    return current_app.config["GOOGLE_MAPS_API_KEY"]


def _session_dir(task_id: str) -> str:
    d = Path(_workspace()) / "sessions" / task_id
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _parse_cert_field(content: str, label: str) -> str:
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == label and i + 1 < len(lines):
            return lines[i + 1].strip()
    return ""


def _extract_license_text(txt_content: str) -> str:
    if "PIXABAY LICENSE CERTIFICATE" in txt_content:
        title = _parse_cert_field(txt_content, "Audio File Title:")
        author_url = _parse_cert_field(txt_content, "Licensor's Username:")
        source_url = _parse_cert_field(txt_content, "Audio File URL:")
        import re
        slug = author_url.rstrip("/").split("/")[-1] if author_url else ""
        author = re.sub(r"-\d+$", "", slug)  # strip Pixabay numeric user ID suffix
        parts = []
        if title:
            parts.append(f'"{title}"')
        if author:
            parts.append(f"by {author}")
        parts.append("Pixabay License")
        credit = " ".join(parts)
        if source_url:
            credit += f" – {source_url}"
        return credit
    return txt_content.strip()


# ---------------------------------------------------------------------------
# Main page (Step 1 – URL input)
# ---------------------------------------------------------------------------

@wizard.get("/")
def step1():
    return render_template("step1_url.html")


@wizard.post("/step1/submit")
def step1_submit():
    import threading

    maps_url = request.form.get("maps_url", "").strip()
    if not maps_url:
        return render_template("step1_url.html", error="Please enter a Google Maps URL.")

    auto_mode = request.form.get("auto_mode", "0") == "1"
    session["auto_mode"] = auto_mode

    task = task_mod.store.create()
    real_dir = _session_dir(task.task_id)
    t = threading.Thread(
        target=task_mod._fetch_task,
        args=(task, maps_url, _api_key(), real_dir),
        daemon=True,
    )
    t.start()

    session["fetch_task_id"] = task.task_id
    session["maps_url"] = maps_url
    return render_template(
        "fragments/loading_fetch.html",
        task_id=task.task_id,
        pct=0,
        progress="Starting…",
    )


# ---------------------------------------------------------------------------
# Task polling / SSE (kept for backward compat)
# ---------------------------------------------------------------------------

@wizard.get("/tasks/<task_id>/status")
def task_status(task_id: str):
    task = task_mod.store.get(task_id)
    if not task:
        return {"status": "error", "error": "task not found"}, 404
    payload = {
        "status": task.status,
        "progress": task.progress,
        "pct": task.progress_pct,
        "error": task.error,
    }
    if task.status == TaskStatus.DONE:
        result = task.result or {}
        if "video_path" in result:
            payload["redirect_url"] = url_for("wizard.step1")
        elif "youtube_url" in result:
            payload["redirect_url"] = url_for("wizard.step1")
        else:
            payload["redirect_url"] = url_for("wizard.step1")
    return payload


@wizard.get("/tasks/<task_id>/stream")
def task_stream(task_id: str):
    def generate():
        last_pct = -1
        while True:
            task = task_mod.store.get(task_id)
            if not task:
                yield f"data: {json.dumps({'error': 'task not found'})}\n\n"
                return
            if task.progress_pct != last_pct or task.status in (TaskStatus.DONE, TaskStatus.ERROR):
                last_pct = task.progress_pct
                payload = {
                    "status": task.status,
                    "progress": task.progress,
                    "pct": task.progress_pct,
                    "error": task.error,
                }
                yield f"data: {json.dumps(payload)}\n\n"
            if task.status in (TaskStatus.DONE, TaskStatus.ERROR):
                return
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# HTMX poll endpoints – return HTML fragments
# ---------------------------------------------------------------------------

@wizard.get("/tasks/<task_id>/poll/fetch")
def poll_fetch(task_id: str):
    task = task_mod.store.get(task_id)
    if not task:
        return render_template(
            "fragments/loading_fetch.html",
            task_id=task_id, pct=0,
            progress="Error: task not found", error=True,
        )
    if task.status == TaskStatus.ERROR:
        return render_template(
            "fragments/loading_fetch.html",
            task_id=task_id, pct=0,
            progress=f"Error: {task.error}", error=True,
        )
    if task.status != TaskStatus.DONE:
        return render_template(
            "fragments/loading_fetch.html",
            task_id=task_id,
            pct=task.progress_pct or 0,
            progress=task.progress or "…",
        )

    result = task.result
    workspace = _workspace()
    thumb_urls = []
    for p in result.get("thumbnail_paths", []):
        rel = os.path.relpath(p, workspace)
        thumb_urls.append(url_for("media.serve_media", filename=rel))

    from ...main import make_title, make_description

    suggested_title = make_title(result["business_name"], result["rating"])
    suggested_description = make_description(
        result["business_name"],
        result["rating"],
        session.get("maps_url", ""),
        result.get("website_url", ""),
    )

    _excluded_music = {"artmanzh-battonya-balkan-music-330439.mp3"}
    mp3_dir = Path(current_app.config.get("PROJECT_ROOT", "")) / "mp3"
    preset_music = (
        sorted(p.name for p in mp3_dir.glob("*.mp3") if p.name not in _excluded_music)
        if mp3_dir.exists() else []
    )

    import random
    auto_preset_music = random.choice(preset_music) if preset_music else ""

    from ..routes.gphotos_oauth import get_or_refresh_gp_credentials

    gp_authed = get_or_refresh_gp_credentials(result["session_dir"]) is not None

    return render_template(
        "fragments/step2_block.html",
        fetch_task_id=task_id,
        business_name=result["business_name"],
        rating=result["rating"],
        review_count=result.get("review_count", 0),
        reviews=result.get("reviews", []),
        thumb_urls=thumb_urls,
        preset_music=preset_music,
        suggested_title=suggested_title,
        suggested_description=suggested_description,
        gp_authed=gp_authed,
        has_location=bool(result.get("lat") and result.get("lng")),
        auto_mode=session.get("auto_mode", False),
        auto_preset_music=auto_preset_music,
    )


@wizard.get("/tasks/<task_id>/poll/generate")
def poll_generate(task_id: str):
    task = task_mod.store.get(task_id)
    _title = session.get("title_override", "")
    _music = session.get("music_copyright", "")
    if not task:
        return render_template(
            "fragments/loading_generate.html",
            task_id=task_id, pct=0,
            progress="Error: task not found", error=True,
            title="", music_copyright="",
        )
    if task.status == TaskStatus.ERROR:
        return render_template(
            "fragments/loading_generate.html",
            task_id=task_id, pct=0,
            progress=f"Error: {task.error}", error=True,
            title=_title, music_copyright=_music,
        )
    if task.status != TaskStatus.DONE:
        return render_template(
            "fragments/loading_generate.html",
            task_id=task_id,
            pct=task.progress_pct or 0,
            progress=task.progress or "…",
            title=_title, music_copyright=_music,
        )

    result = task.result
    workspace = _workspace()
    video_rel = os.path.relpath(result["video_path"], workspace)
    video_url = url_for("media.serve_media", filename=video_rel)

    from ..routes.youtube_oauth import get_or_refresh_credentials
    creds = get_or_refresh_credentials()

    return render_template(
        "fragments/step3_block.html",
        video_url=video_url,
        title=session.get("title_override", ""),
        yt_authed=creds is not None,
    )


@wizard.get("/tasks/<task_id>/poll/publish")
def poll_publish(task_id: str):
    task = task_mod.store.get(task_id)
    if not task:
        return render_template("fragments/publish_result.html", error="Task not found.", youtube_url=None, title="")
    if task.status == TaskStatus.ERROR:
        return render_template("fragments/publish_result.html", error=task.error, youtube_url=None, title="")
    if task.status != TaskStatus.DONE:
        return render_template(
            "fragments/publish_loading.html",
            task_id=task_id,
            pct=task.progress_pct or 0,
            progress=task.progress or "Uploading…",
        )
    return render_template(
        "fragments/publish_result.html",
        youtube_url=task.result.get("youtube_url"),
        title=session.get("title_override", ""),
        error=None,
    )


# ---------------------------------------------------------------------------
# Step 2 – merged select + arrange + music + params (HTMX)
# ---------------------------------------------------------------------------

@wizard.post("/step2/submit")
def step2_submit():
    review_idx = int(request.form.get("review_idx", 0))
    photo_order = request.form.getlist("photo_order")
    music_copyright = request.form.get("music_copyright", "").strip()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()

    session["selected_review_idx"] = review_idx
    session["photo_order"] = photo_order
    session["music_copyright"] = music_copyright
    session["title_override"] = title
    session["description_override"] = description

    music_path: str | None = None
    music_file = request.files.get("music_file")
    if music_file and music_file.filename:
        music_dir = Path(_workspace()) / "music"
        music_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(music_file.filename).name
        dest = music_dir / safe_name
        music_file.save(str(dest))
        music_path = str(dest)
    else:
        preset = request.form.get("preset_music", "")
        if preset:
            mp3_dir = Path(current_app.config.get("PROJECT_ROOT", "")) / "mp3"
            candidate = mp3_dir / preset
            if candidate.exists():
                music_path = str(candidate)

    session["music_path"] = music_path

    def _float(name: str, default: float) -> float:
        try:
            return float(request.form.get(name, default))
        except (ValueError, TypeError):
            return default

    card_config = {
        "intro":  {
            "enabled":  bool(request.form.get("card_intro_enabled")),
            "duration": _float("card_intro_duration", 2.0),
        },
        "review": {
            "enabled":  bool(request.form.get("card_review_enabled")),
            "duration": _float("card_review_duration", 4.0),
        },
        "map":    {
            "enabled":  bool(request.form.get("card_map_enabled")),
            "duration": _float("card_map_duration", 3.0),
        },
        "outro":  {
            "enabled":      bool(request.form.get("card_outro_enabled")),
            "duration":     _float("card_outro_duration", 5.0),
            "show_qr":      bool(request.form.get("card_outro_qr")),
            "show_website": bool(request.form.get("card_outro_website")),
        },
    }
    session["card_config"] = card_config

    # Use hidden form field first (survives session loss), fall back to session cookie
    fetch_task_id = request.form.get("fetch_task_id") or session.get("fetch_task_id")
    fetch_task = task_mod.store.get(fetch_task_id) if fetch_task_id else None
    if not fetch_task or fetch_task.status != TaskStatus.DONE:
        return render_template("fragments/error_block.html",
                               message="Session expired or place data lost. Please start over."), 200

    result = fetch_task.result
    reviews = result.get("reviews", [])
    selected_review = reviews[review_idx] if reviews and review_idx < len(reviews) else {}

    photo_source = request.form.get("photo_source", "places")

    if photo_source == "gphotos":
        gp_baseurls = request.form.getlist("gp_photo_baseurls")[:5]
        if not gp_baseurls:
            return render_template(
                "fragments/error_block.html",
                message="No Google Photos selected. Please select at least one photo.",
            ), 200
        gen_task = task_mod.run_in_thread(
            task_mod._generate_task_gphotos,
            result["session_dir"],
            result,
            gp_baseurls,
            selected_review,
            music_path,
            0.0,
            session.get("maps_url", ""),
            card_config,
        )
    else:
        try:
            photo_indices = [int(x) for x in photo_order]
        except (ValueError, TypeError):
            photo_indices = list(range(min(5, len(result.get("raw_photos", [])))))

        gen_task = task_mod.run_in_thread(
            task_mod._generate_task,
            result["session_dir"],
            result,
            photo_indices,
            selected_review,
            _api_key(),
            music_path,
            0.0,
            session.get("maps_url", ""),
            card_config,
        )

    session["generate_task_id"] = gen_task.task_id
    return render_template(
        "fragments/loading_generate.html",
        task_id=gen_task.task_id,
        pct=0,
        progress="Starting…",
        title=title,
        music_copyright=music_copyright,
    )


# ---------------------------------------------------------------------------
# API – music license text
# ---------------------------------------------------------------------------

@wizard.get("/api/mp3-license/<stem>")
def mp3_license(stem: str):
    if "/" in stem or "\\" in stem or ".." in stem:
        return {"text": ""}, 400
    mp3_dir = Path(current_app.config.get("PROJECT_ROOT", "")) / "mp3"
    txt_path = mp3_dir / f"{Path(stem).stem}.txt"
    if not txt_path.exists():
        return {"text": ""}
    content = txt_path.read_text(encoding="utf-8")
    return {"text": _extract_license_text(content)}


@wizard.get("/api/mp3/<filename>")
def serve_mp3(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        abort(400)
    if not filename.lower().endswith(".mp3"):
        abort(400)
    mp3_dir = Path(current_app.config.get("PROJECT_ROOT", "")) / "mp3"
    return send_from_directory(str(mp3_dir), filename)


# ---------------------------------------------------------------------------
# Publish (HTMX)
# ---------------------------------------------------------------------------

@wizard.post("/step5/publish")
def step5_publish():
    gen_task_id = session.get("generate_task_id")
    if not gen_task_id:
        return render_template("fragments/publish_result.html", error="No video generated. Start over.")
    gen_task = task_mod.store.get(gen_task_id)
    if not gen_task or gen_task.status != TaskStatus.DONE:
        return render_template("fragments/publish_result.html", error="Video not ready.")

    result = gen_task.result
    title = session.get("title_override", "")
    description = session.get("description_override", "")
    music_copyright = session.get("music_copyright", "")
    if music_copyright:
        description += f"\n\n\U0001f3b5 {music_copyright}"

    pub_task = task_mod.run_in_thread(
        task_mod._publish_task,
        result["video_path"],
        title,
        description,
        result["metadata_path"],
    )
    session["publish_task_id"] = pub_task.task_id
    return render_template(
        "fragments/publish_loading.html",
        task_id=pub_task.task_id,
        pct=0,
        progress="Uploading to YouTube…",
    )


# ---------------------------------------------------------------------------
# Legacy redirects
# ---------------------------------------------------------------------------

@wizard.get("/step2")
def step2():
    return redirect(url_for("wizard.step1"))


@wizard.get("/step3")
def step3():
    return redirect(url_for("wizard.step1"))


@wizard.get("/step4")
def step4():
    return redirect(url_for("wizard.step1"))


@wizard.get("/step5")
def step5():
    return redirect(url_for("wizard.step1"))
