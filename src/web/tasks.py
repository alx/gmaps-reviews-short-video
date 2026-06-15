import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

from .. import gmaps
from .. import video as video_mod

# ---------------------------------------------------------------------------
# Sidecar helpers
# ---------------------------------------------------------------------------

_SIDECAR_PORT = int(os.getenv("SIDECAR_PORT", "3001"))
_SIDECAR_BASE = f"http://127.0.0.1:{_SIDECAR_PORT}"
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)


def _asset_url(path: str) -> str:
    """Convert an absolute local path to a sidecar /assets/ URL."""
    rel = os.path.relpath(path, _PROJECT_ROOT)
    return f"{_SIDECAR_BASE}/assets/{rel}"


VALID_VIBES = {"restaurant", "medical", "retail", "other"}


def _build_input_props(
    place_data: dict,
    photo_paths: list[str],
    selected_review: dict,
    music_path: str | None,
    maps_url: str,
    card_config: dict | None,
    map_image_url: str,
    industry_vibe: str = "other",
) -> dict:
    cfg = card_config or {}
    ci = cfg.get("intro", {})
    cr = cfg.get("review", {})
    cm = cfg.get("map", {})
    co = cfg.get("outro", {})
    vibe = industry_vibe if industry_vibe in VALID_VIBES else "other"
    return {
        "businessName": place_data["business_name"],
        "rating": float(place_data["rating"]),
        "city": place_data.get("city", ""),
        "country": place_data.get("country", ""),
        "countryCode": place_data.get("country_code", ""),
        "websiteUrl": place_data.get("website_url", ""),
        "mapsUrl": maps_url or "",
        "review": selected_review if selected_review else None,
        "photoUrls": [_asset_url(p) for p in photo_paths],
        "mapImageUrl": map_image_url,
        "musicUrl": _asset_url(music_path) if music_path else "",
        "musicOffset": 0.0,
        "industryVibe": vibe,
        "cards": {
            "intro":  {"enabled": bool(ci.get("enabled", True))},
            "review": {"enabled": bool(cr.get("enabled", True)) and bool(selected_review)},
            "map":    {"enabled": bool(cm.get("enabled", True)) and bool(map_image_url)},
            "outro":  {
                "enabled":     bool(co.get("enabled", True)),
                "showQr":      bool(co.get("show_qr", True)),
                "showWebsite": bool(co.get("show_website", True)),
            },
        },
    }


def _render_via_sidecar(task: "TaskState", input_props: dict, output_path: str) -> None:
    """POST a render job to the sidecar and poll until done, updating task progress."""
    resp = httpx.post(
        f"{_SIDECAR_BASE}/render",
        json={"outputPath": output_path, "inputProps": input_props},
        timeout=15,
    )
    resp.raise_for_status()
    job_id = resp.json()["jobId"]

    while True:
        prog = httpx.get(f"{_SIDECAR_BASE}/jobs/{job_id}", timeout=10).json()
        pct = 40 + int(prog["progress"] * 55)  # maps 0→1 into 40%→95%
        store.update(task.task_id, progress_pct=pct)
        if prog["done"]:
            if prog["error"]:
                raise RuntimeError(prog["error"])
            break
        time.sleep(1)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class TaskState:
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: str = ""
    progress_pct: int = 0
    result: dict = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)


class TaskStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskState] = {}

    def create(self) -> TaskState:
        task_id = str(uuid.uuid4())
        task = TaskState(task_id=task_id)
        with self._lock:
            self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> TaskState | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **kwargs) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                for k, v in kwargs.items():
                    setattr(task, k, v)

    def cleanup_old(self, max_age_hours: int = 24) -> None:
        cutoff = time.time() - max_age_hours * 3600
        with self._lock:
            stale = [tid for tid, t in self._tasks.items() if t.created_at < cutoff]
            for tid in stale:
                del self._tasks[tid]


store = TaskStore()


def run_in_thread(fn, *args, **kwargs) -> TaskState:
    task = store.create()
    t = threading.Thread(target=fn, args=(task, *args), kwargs=kwargs, daemon=True)
    t.start()
    return task


def _fetch_task(task: TaskState, url: str, api_key: str, session_dir: str) -> None:
    logger.info("[task:%s] fetch started url=%s", task.task_id[:8], url)
    store.update(task.task_id, status=TaskStatus.RUNNING, progress="Fetching place data…", progress_pct=10)
    cache_dir = str(Path(session_dir).parent.parent / "place_cache")
    try:
        meta = gmaps.fetch_place_metadata(url, api_key, cache_dir=cache_dir)
    except Exception as exc:
        logger.error("[task:%s] fetch place metadata failed: %s", task.task_id[:8], exc)
        store.update(task.task_id, status=TaskStatus.ERROR, error=str(exc))
        return

    logger.info("[task:%s] place metadata fetched: %s", task.task_id[:8], meta.get("business_name", ""))
    store.update(task.task_id, progress="Downloading photo previews…", progress_pct=40)
    thumb_dir = Path(session_dir) / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    try:
        thumb_paths = gmaps.download_selected_photos(
            meta["raw_photos"], api_key, str(thumb_dir),
            indices=None, max_photos=10, width=400, height=711,
        )
    except Exception as exc:
        logger.error("[task:%s] photo download failed: %s", task.task_id[:8], exc)
        store.update(task.task_id, status=TaskStatus.ERROR, error=f"Photo download failed: {exc}")
        return

    logger.info("[task:%s] fetch done: %d thumbnails", task.task_id[:8], len(thumb_paths))
    store.update(
        task.task_id,
        status=TaskStatus.DONE,
        progress="Done",
        progress_pct=100,
        result={**meta, "thumbnail_paths": thumb_paths, "session_dir": session_dir},
    )


def _run_generate_core(
    task: TaskState,
    session_dir: str,
    place_data: dict,
    photo_paths: list[str],
    selected_review: dict,
    music_path: str | None,
    maps_url: str,
    card_config: dict | None,
    industry_vibe: str,
    extra_metadata: dict | None = None,
) -> None:
    import datetime
    import json

    cfg = card_config or {}
    map_image_url = ""
    if cfg.get("map", {}).get("enabled", True) and place_data.get("lat") and place_data.get("lng"):
        store.update(task.task_id, progress="Rendering map…", progress_pct=25)
        map_path = str(Path(session_dir) / "map.png")
        result = video_mod.render_map_image(place_data["lat"], place_data["lng"], map_path)
        if result:
            map_image_url = _asset_url(map_path)

    store.update(task.task_id, progress=f"Generating {industry_vibe}-style video…", progress_pct=40)
    output_path = str(Path(session_dir) / "video.mp4")
    input_props = _build_input_props(
        place_data, photo_paths, selected_review, music_path, maps_url, card_config,
        map_image_url, industry_vibe,
    )
    try:
        _render_via_sidecar(task, input_props, output_path)
    except Exception as exc:
        logger.exception("[task:%s] video generation failed: %s", task.task_id[:8], exc)
        store.update(task.task_id, status=TaskStatus.ERROR, error=f"Video generation failed: {exc}")
        return

    logger.info(
        "[task:%s] video_generated business=%s vibe=%s",
        task.task_id[:8], place_data.get("business_name", ""), industry_vibe,
    )
    store.update(task.task_id, progress="Saving metadata…", progress_pct=95)
    metadata: dict = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "maps_url": maps_url,
        "business_name": place_data["business_name"],
        "rating": place_data["rating"],
        "review_count": place_data["review_count"],
        "website_url": place_data.get("website_url", ""),
        "review": selected_review or None,
        "photo_count": len(photo_paths),
        "industry_vibe": industry_vibe,
        "music": music_path,
        "output_video": output_path,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    metadata_path = str(Path(session_dir) / "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    store.update(
        task.task_id,
        status=TaskStatus.DONE,
        progress="Done",
        progress_pct=100,
        result={
            "video_path": output_path,
            "metadata_path": metadata_path,
            "metadata": metadata,
        },
    )


def _generate_task(
    task: TaskState,
    session_dir: str,
    place_data: dict,
    photo_indices: list[int],
    selected_review: dict,
    api_key: str,
    music_path: str | None,
    music_offset: float,
    maps_url: str,
    card_config: dict | None = None,
    industry_vibe: str = "other",
) -> None:
    logger.info(
        "[task:%s] generate started business=%s vibe=%s",
        task.task_id[:8], place_data.get("business_name", ""), industry_vibe,
    )
    store.update(task.task_id, status=TaskStatus.RUNNING, progress="Downloading full-res photos…", progress_pct=10)
    photo_dir = Path(session_dir) / "photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    try:
        photo_paths = gmaps.download_selected_photos(
            place_data["raw_photos"], api_key, str(photo_dir),
            indices=photo_indices, max_photos=10,
        )
    except Exception as exc:
        logger.error("[task:%s] photo download failed: %s", task.task_id[:8], exc)
        store.update(task.task_id, status=TaskStatus.ERROR, error=f"Photo download failed: {exc}")
        return

    logger.info("[task:%s] photos downloaded: %d files", task.task_id[:8], len(photo_paths))
    _run_generate_core(
        task, session_dir, place_data, photo_paths, selected_review,
        music_path, maps_url, card_config, industry_vibe,
    )


def _generate_task_gphotos(
    task: TaskState,
    session_dir: str,
    place_data: dict,
    gp_baseurls: list[str],
    selected_review: dict,
    music_path: str | None,
    music_offset: float,
    maps_url: str,
    card_config: dict | None = None,
    industry_vibe: str = "other",
) -> None:
    logger.info(
        "[task:%s] generate_gphotos started business=%s vibe=%s",
        task.task_id[:8], place_data.get("business_name", ""), industry_vibe,
    )
    store.update(task.task_id, status=TaskStatus.RUNNING, progress="Downloading Google Photos…", progress_pct=10)
    photo_dir = Path(session_dir) / "photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    photo_paths: list[str] = []
    for slot, base_url in enumerate(gp_baseurls[:5]):
        try:
            resp = httpx.get(base_url + "=w1080-h1920-c", follow_redirects=True, timeout=30)
            resp.raise_for_status()
            out = photo_dir / f"photo_{slot}.jpg"
            out.write_bytes(resp.content)
            photo_paths.append(str(out))
        except Exception as exc:
            logger.error("[task:%s] photo download failed (slot %d): %s", task.task_id[:8], slot, exc)
            store.update(task.task_id, status=TaskStatus.ERROR, error=f"Photo download failed: {exc}")
            return

    logger.info("[task:%s] photos downloaded: %d files", task.task_id[:8], len(photo_paths))
    _run_generate_core(
        task, session_dir, place_data, photo_paths, selected_review,
        music_path, maps_url, card_config, industry_vibe,
        extra_metadata={"photo_source": "google_photos"},
    )


def _publish_task(
    task: TaskState,
    video_path: str,
    title: str,
    description: str,
    metadata_path: str,
) -> None:
    import json
    from .. import youtube

    store.update(task.task_id, status=TaskStatus.RUNNING, progress="Authenticating with YouTube…", progress_pct=10)
    try:
        service = youtube.authenticate()
    except Exception as exc:
        store.update(task.task_id, status=TaskStatus.ERROR, error=f"YouTube auth failed: {exc}")
        return

    store.update(task.task_id, progress="Uploading video…", progress_pct=30)
    try:
        yt_url = youtube.upload_video(service, video_path, title=title, description=description)
    except Exception as exc:
        store.update(task.task_id, status=TaskStatus.ERROR, error=f"Upload failed: {exc}")
        return

    try:
        with open(metadata_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["youtube_url"] = yt_url
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    except OSError:
        pass

    store.update(
        task.task_id,
        status=TaskStatus.DONE,
        progress="Published",
        progress_pct=100,
        result={"youtube_url": yt_url},
    )


