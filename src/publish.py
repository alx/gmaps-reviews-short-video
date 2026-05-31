#!/usr/bin/env python3
"""
Publish the most recently generated videos to YouTube without re-running the pipeline.

Usage:
  uv run python -m src.publish
  uv run python -m src.publish --count 4 --dir output
  uv run python -m src.publish --force   # re-publish even if youtube_url already set
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .main import make_description, make_title
from . import youtube


def _load_sidecar(mp4: Path) -> dict | None:
    json_path = mp4.with_suffix(".json")
    if not json_path.exists():
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_sidecar(mp4: Path, meta: dict) -> None:
    json_path = mp4.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Publish the most recently generated videos to YouTube"
    )
    parser.add_argument(
        "--count", type=int, default=4,
        help="Number of videos to publish (default: 4)",
    )
    parser.add_argument(
        "--dir", default="output", metavar="DIR",
        help="Directory to scan for MP4 files (default: output)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-publish even if youtube_url is already set in the sidecar",
    )
    parser.add_argument(
        "--music-copyright", metavar="TEXT", default="",
        help="Music copyright notice appended to the YouTube description",
    )
    args = parser.parse_args()

    output_dir = Path(args.dir)
    if not output_dir.is_dir():
        print(f"Error: directory not found: {output_dir}", file=sys.stderr)
        sys.exit(1)

    # Collect MP4s that have a JSON sidecar, sort newest first
    candidates: list[tuple[str, Path, dict]] = []
    for mp4 in sorted(output_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = _load_sidecar(mp4)
        if meta is None:
            continue
        generated_at = meta.get("generated_at", "")
        candidates.append((generated_at, mp4, meta))

    candidates.sort(key=lambda t: t[0], reverse=True)

    if not args.force:
        candidates = [(g, p, m) for g, p, m in candidates if not m.get("youtube_url")]

    if not candidates:
        print("No publishable videos found (all already published; use --force to re-publish).")
        return

    to_publish = candidates[: args.count]
    print(f"Found {len(candidates)} unpublished video(s), publishing {len(to_publish)}.")

    service = youtube.authenticate()

    for generated_at, mp4, meta in to_publish:
        business_name = meta.get("business_name", mp4.stem)
        rating = float(meta.get("rating") or 0)
        maps_url = meta.get("maps_url", "")
        website_url = meta.get("website_url", "")
        category = meta.get("category", "")

        title = make_title(business_name, rating, category)
        description = make_description(
            business_name, rating, maps_url, website_url, category,
            music_copyright=args.music_copyright,
        )

        print(f"Uploading {mp4.name} …")
        try:
            yt_url = youtube.upload_video(service, str(mp4), title=title, description=description)
            meta["youtube_url"] = yt_url
            _save_sidecar(mp4, meta)
            print(f"  Published → {yt_url}")
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
