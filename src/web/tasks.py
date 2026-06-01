import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .. import gmaps
from .. import video as video_mod


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
    store.update(task.task_id, status=TaskStatus.RUNNING, progress="Fetching place data…", progress_pct=10)
    try:
        meta = gmaps.fetch_place_metadata(url, api_key)
    except Exception as exc:
        store.update(task.task_id, status=TaskStatus.ERROR, error=str(exc))
        return

    store.update(task.task_id, progress="Downloading photo previews…", progress_pct=40)
    thumb_dir = Path(session_dir) / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    try:
        thumb_paths = gmaps.download_selected_photos(
            meta["raw_photos"], api_key, str(thumb_dir),
            indices=None, max_photos=10, width=400, height=711,
        )
    except Exception as exc:
        store.update(task.task_id, status=TaskStatus.ERROR, error=f"Photo download failed: {exc}")
        return

    store.update(
        task.task_id,
        status=TaskStatus.DONE,
        progress="Done",
        progress_pct=100,
        result={**meta, "thumbnail_paths": thumb_paths, "session_dir": session_dir},
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
) -> None:
    import datetime
    import json

    store.update(task.task_id, status=TaskStatus.RUNNING, progress="Downloading full-res photos…", progress_pct=10)
    photo_dir = Path(session_dir) / "photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    try:
        photo_paths = gmaps.download_selected_photos(
            place_data["raw_photos"], api_key, str(photo_dir),
            indices=photo_indices, max_photos=10,
        )
    except Exception as exc:
        store.update(task.task_id, status=TaskStatus.ERROR, error=f"Photo download failed: {exc}")
        return

    store.update(task.task_id, progress="Generating video…", progress_pct=40)
    output_path = str(Path(session_dir) / "video.mp4")
    try:
        video_mod.build_video(
            business_name=place_data["business_name"],
            rating=place_data["rating"],
            photo_paths=photo_paths,
            reviews=[selected_review] if selected_review else [],
            output_path=output_path,
            website_url=place_data.get("website_url", ""),
            music_path=music_path,
            maps_url=maps_url,
            music_offset=music_offset,
            city=place_data.get("city", ""),
            country=place_data.get("country", ""),
            country_code=place_data.get("country_code", ""),
            lat=place_data.get("lat"),
            lng=place_data.get("lng"),
            card_config=card_config or {},
        )
    except Exception as exc:
        store.update(task.task_id, status=TaskStatus.ERROR, error=f"Video generation failed: {exc}")
        return

    store.update(task.task_id, progress="Saving metadata…", progress_pct=90)
    metadata = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "maps_url": maps_url,
        "business_name": place_data["business_name"],
        "rating": place_data["rating"],
        "review_count": place_data["review_count"],
        "website_url": place_data.get("website_url", ""),
        "review": selected_review or None,
        "photo_count": len(photo_paths),
        "music": music_path,
        "output_video": output_path,
    }
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
) -> None:
    import datetime
    import json

    import httpx

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
            store.update(task.task_id, status=TaskStatus.ERROR, error=f"Photo download failed: {exc}")
            return

    store.update(task.task_id, progress="Generating video…", progress_pct=40)
    output_path = str(Path(session_dir) / "video.mp4")
    try:
        video_mod.build_video(
            business_name=place_data["business_name"],
            rating=place_data["rating"],
            photo_paths=photo_paths,
            reviews=[selected_review] if selected_review else [],
            output_path=output_path,
            website_url=place_data.get("website_url", ""),
            music_path=music_path,
            maps_url=maps_url,
            music_offset=music_offset,
            city=place_data.get("city", ""),
            country=place_data.get("country", ""),
            country_code=place_data.get("country_code", ""),
            lat=place_data.get("lat"),
            lng=place_data.get("lng"),
            card_config=card_config or {},
        )
    except Exception as exc:
        store.update(task.task_id, status=TaskStatus.ERROR, error=f"Video generation failed: {exc}")
        return

    store.update(task.task_id, progress="Saving metadata…", progress_pct=90)
    metadata = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "maps_url": maps_url,
        "business_name": place_data["business_name"],
        "rating": place_data["rating"],
        "review_count": place_data["review_count"],
        "website_url": place_data.get("website_url", ""),
        "review": selected_review or None,
        "photo_count": len(photo_paths),
        "photo_source": "google_photos",
        "music": music_path,
        "output_video": output_path,
    }
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
