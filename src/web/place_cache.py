"""
Place cache: persistent per-place directory storing metadata, thumbnails, and
an index of sessions where a video was generated for that place.

Layout:
  web_workspace/
    place_cache/{place_id}/
      meta.json          ← place metadata (reviews, rating, raw_photos, …)
      images/
        thumb_{n}.jpg    ← 400×711 thumbnail (n = raw_photos index)
        custom_{name}    ← user-uploaded image
    place_index/
      {place_id}.json    ← ordered list of session UUIDs

Image filenames encode origin:
  thumb_{n}.jpg   → API photo at index n in raw_photos (full-res downloadable)
  custom_{name}   → user-uploaded; used directly at generation time
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def _place_dir(cache_root: str, place_id: str) -> Path:
    return Path(cache_root) / place_id


def _meta_path(cache_root: str, place_id: str) -> Path:
    return _place_dir(cache_root, place_id) / "meta.json"


def _images_dir(cache_root: str, place_id: str) -> Path:
    return _place_dir(cache_root, place_id) / "images"


def load_meta(cache_root: str, place_id: str) -> dict | None:
    p = _meta_path(cache_root, place_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    # migrate old flat file
    old = Path(cache_root) / f"{place_id}.json"
    if old.exists():
        data = json.loads(old.read_text(encoding="utf-8"))
        save_meta(cache_root, place_id, data)
        old.unlink(missing_ok=True)
        return data
    return None


def save_meta(cache_root: str, place_id: str, data: dict) -> None:
    p = _meta_path(cache_root, place_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Image cache helpers
# ---------------------------------------------------------------------------

def images_dir(cache_root: str, place_id: str) -> Path:
    d = _images_dir(cache_root, place_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_images(cache_root: str, place_id: str) -> list[Path]:
    """Return sorted list of image paths: API thumbs first (by index), then custom."""
    d = _images_dir(cache_root, place_id)
    if not d.exists():
        return []
    api_imgs: list[tuple[int, Path]] = []
    custom_imgs: list[Path] = []
    for p in d.iterdir():
        if not p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        if p.name.startswith("thumb_"):
            try:
                idx = int(p.stem.split("_", 1)[1])
                api_imgs.append((idx, p))
            except (ValueError, IndexError):
                custom_imgs.append(p)
        else:
            custom_imgs.append(p)
    api_imgs.sort(key=lambda x: x[0])
    return [p for _, p in api_imgs] + sorted(custom_imgs)


def copy_thumbnails(cache_root: str, place_id: str, thumb_paths: list[str]) -> list[str]:
    """Copy session thumbnails into the place cache.

    thumb_paths must be ordered by raw_photos index (photo_0.jpg → thumb_0, …).
    Already-cached thumbs are skipped. Returns paths of cached images in order.
    """
    dest_dir = images_dir(cache_root, place_id)
    cached: list[str] = []
    for i, src in enumerate(thumb_paths):
        dest = dest_dir / f"thumb_{i}.jpg"
        if not dest.exists():
            shutil.copy2(src, dest)
        cached.append(str(dest))
    return cached


def cached_thumb_paths(cache_root: str, place_id: str) -> list[str]:
    """Return all API thumbnail paths from place cache, sorted by index."""
    return [str(p) for p in list_images(cache_root, place_id) if p.name.startswith("thumb_")]


def api_index_from_filename(filename: str) -> int | None:
    """Parse 'thumb_3.jpg' → 3, anything else → None."""
    stem = Path(filename).stem
    if stem.startswith("thumb_"):
        try:
            return int(stem[6:])
        except ValueError:
            pass
    return None


def save_custom_image(cache_root: str, place_id: str, data: bytes, original_name: str) -> str:
    """Save a user-uploaded image. Returns the stored filename."""
    ext = Path(original_name).suffix.lower() or ".jpg"
    name = f"custom_{uuid.uuid4().hex[:8]}{ext}"
    dest = images_dir(cache_root, place_id) / name
    dest.write_bytes(data)
    return name


def delete_image(cache_root: str, place_id: str, filename: str) -> bool:
    """Delete an image from the place cache. Returns True if deleted."""
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    p = _images_dir(cache_root, place_id) / filename
    if p.exists():
        p.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Place index (session → place mapping)
# ---------------------------------------------------------------------------

def _index_path(workspace_root: str, place_id: str) -> Path:
    return Path(workspace_root) / "place_index" / f"{place_id}.json"


def append_session(workspace_root: str, place_id: str, session_id: str) -> None:
    p = _index_path(workspace_root, place_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    sessions: list[str] = []
    if p.exists():
        try:
            sessions = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            sessions = []
    if session_id not in sessions:
        sessions.append(session_id)
    p.write_text(json.dumps(sessions, indent=2), encoding="utf-8")


def past_videos(workspace_root: str, place_id: str) -> list[dict]:
    """Return metadata dicts for sessions that have a completed video, newest first."""
    p = _index_path(workspace_root, place_id)
    if not p.exists():
        return []
    try:
        session_ids: list[str] = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    sessions_root = Path(workspace_root) / "sessions"
    results: list[dict] = []
    for sid in reversed(session_ids):
        session_dir = sessions_root / sid
        video = session_dir / "video.mp4"
        if not video.exists():
            continue
        meta_file = session_dir / "metadata.json"
        meta: dict = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        results.append({
            "session_id": sid,
            "video_rel": f"sessions/{sid}/video.mp4",
            "generated_at": meta.get("generated_at", ""),
            "business_name": meta.get("business_name", ""),
        })
    return results
