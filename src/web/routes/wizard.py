import json
import os
import time
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    current_app,
    redirect,
    render_template,
    request,
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


# ---------------------------------------------------------------------------
# Step 1 – URL input
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

    # Create task first to get its ID, then derive session dir from it
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
    return redirect(url_for("wizard.step1_wait"))


@wizard.get("/step1/wait")
def step1_wait():
    task_id = session.get("fetch_task_id")
    if not task_id:
        return redirect(url_for("wizard.step1"))
    return render_template("step1_wait.html", task_id=task_id)


# ---------------------------------------------------------------------------
# Task polling / SSE
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
        # Decide where to redirect based on what kind of task this is
        result = task.result or {}
        if "video_path" in result:
            payload["redirect_url"] = url_for("wizard.step4")
        elif "youtube_url" in result:
            payload["redirect_url"] = url_for("wizard.step5")
        else:
            payload["redirect_url"] = url_for("wizard.step2")
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
# Step 2 – Select review + photos
# ---------------------------------------------------------------------------

@wizard.get("/step2")
def step2():
    task_id = session.get("fetch_task_id")
    if not task_id:
        return redirect(url_for("wizard.step1"))
    task = task_mod.store.get(task_id)
    if not task or task.status != TaskStatus.DONE:
        return redirect(url_for("wizard.step1_wait"))

    result = task.result
    reviews = result.get("reviews", [])
    thumb_paths = result.get("thumbnail_paths", [])

    # Build media-relative paths for templates
    workspace = _workspace()
    thumb_urls = []
    for p in thumb_paths:
        rel = os.path.relpath(p, workspace)
        thumb_urls.append(url_for("media.serve_media", filename=rel))

    return render_template(
        "step2_select.html",
        business_name=result.get("business_name", ""),
        rating=result.get("rating", 0),
        review_count=result.get("review_count", 0),
        reviews=reviews,
        thumb_urls=thumb_urls,
    )


@wizard.post("/step2/submit")
def step2_submit():
    review_idx = int(request.form.get("review_idx", 0))
    photo_order = request.form.getlist("photo_order")
    session["selected_review_idx"] = review_idx
    session["photo_order"] = photo_order
    return redirect(url_for("wizard.step3"))


# ---------------------------------------------------------------------------
# Step 3 – Video parameters
# ---------------------------------------------------------------------------

@wizard.get("/step3")
def step3():
    task_id = session.get("fetch_task_id")
    if not task_id:
        return redirect(url_for("wizard.step1"))
    task = task_mod.store.get(task_id)
    if not task or task.status != TaskStatus.DONE:
        return redirect(url_for("wizard.step1_wait"))

    result = task.result
    from ...main import make_title, make_description

    suggested_title = make_title(result["business_name"], result["rating"])
    suggested_description = make_description(
        result["business_name"],
        result["rating"],
        session.get("maps_url", ""),
        result.get("website_url", ""),
    )

    # List preset music files from mp3/ directory
    mp3_dir = Path(current_app.config.get("PROJECT_ROOT", "")) / "mp3"
    preset_music = sorted(mp3_dir.glob("*.mp3")) if mp3_dir.exists() else []

    return render_template(
        "step3_params.html",
        business_name=result["business_name"],
        suggested_title=suggested_title,
        suggested_description=suggested_description,
        preset_music=[p.name for p in preset_music],
    )


@wizard.post("/step3/submit")
def step3_submit():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    music_copyright = request.form.get("music_copyright", "").strip()

    # Handle music: uploaded file takes priority over preset selection
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
    session["music_copyright"] = music_copyright
    session["title_override"] = title
    session["description_override"] = description

    # Look up place data from the fetch task
    fetch_task_id = session.get("fetch_task_id")
    fetch_task = task_mod.store.get(fetch_task_id) if fetch_task_id else None
    if not fetch_task or fetch_task.status != TaskStatus.DONE:
        return redirect(url_for("wizard.step1"))

    result = fetch_task.result
    review_idx = session.get("selected_review_idx", 0)
    reviews = result.get("reviews", [])
    selected_review = reviews[review_idx] if reviews and review_idx < len(reviews) else {}

    photo_order_raw = session.get("photo_order", [])
    try:
        photo_indices = [int(x) for x in photo_order_raw]
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
    )
    session["generate_task_id"] = gen_task.task_id
    return redirect(url_for("wizard.step4_wait"))


# ---------------------------------------------------------------------------
# Step 4 – Video preview
# ---------------------------------------------------------------------------

@wizard.get("/step4/wait")
def step4_wait():
    task_id = session.get("generate_task_id")
    if not task_id:
        return redirect(url_for("wizard.step3"))
    return render_template("step4_wait.html", task_id=task_id)


@wizard.get("/step4")
def step4():
    task_id = session.get("generate_task_id")
    if not task_id:
        return redirect(url_for("wizard.step3"))
    task = task_mod.store.get(task_id)
    if not task or task.status != TaskStatus.DONE:
        return redirect(url_for("wizard.step4_wait"))

    result = task.result
    workspace = _workspace()
    video_rel = os.path.relpath(result["video_path"], workspace)
    video_url = url_for("media.serve_media", filename=video_rel)
    metadata_json = json.dumps(result.get("metadata", {}), indent=2, ensure_ascii=False)

    return render_template(
        "step4_preview.html",
        video_url=video_url,
        metadata_json=metadata_json,
        title=session.get("title_override", ""),
        description=session.get("description_override", ""),
    )


# ---------------------------------------------------------------------------
# Step 5 – Publish
# ---------------------------------------------------------------------------

@wizard.get("/step5")
def step5():
    from ..routes.youtube_oauth import get_or_refresh_credentials

    creds = get_or_refresh_credentials()
    youtube_url = session.pop("youtube_url", None)

    publish_task_id = session.get("publish_task_id")
    publish_error = None
    if publish_task_id:
        pub_task = task_mod.store.get(publish_task_id)
        if pub_task and pub_task.status == TaskStatus.DONE:
            youtube_url = pub_task.result.get("youtube_url")
            session["youtube_url"] = youtube_url
        elif pub_task and pub_task.status == TaskStatus.ERROR:
            publish_error = pub_task.error

    return render_template(
        "step5_publish.html",
        yt_authed=creds is not None,
        youtube_url=youtube_url,
        publish_error=publish_error,
        publish_task_id=publish_task_id,
        title=session.get("title_override", ""),
        description=session.get("description_override", ""),
    )


@wizard.post("/step5/publish")
def step5_publish():
    gen_task_id = session.get("generate_task_id")
    if not gen_task_id:
        return redirect(url_for("wizard.step4"))
    gen_task = task_mod.store.get(gen_task_id)
    if not gen_task or gen_task.status != TaskStatus.DONE:
        return redirect(url_for("wizard.step4"))

    result = gen_task.result
    title = session.get("title_override", "")
    description = session.get("description_override", "")
    music_copyright = session.get("music_copyright", "")
    if music_copyright:
        description += f"\n\n🎵 {music_copyright}"

    pub_task = task_mod.run_in_thread(
        task_mod._publish_task,
        result["video_path"],
        title,
        description,
        result["metadata_path"],
    )
    session["publish_task_id"] = pub_task.task_id
    return redirect(url_for("wizard.step5_wait"))


@wizard.get("/step5/wait")
def step5_wait():
    task_id = session.get("publish_task_id")
    if not task_id:
        return redirect(url_for("wizard.step5"))
    return render_template("step5_wait.html", task_id=task_id)
