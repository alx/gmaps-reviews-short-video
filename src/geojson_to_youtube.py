#!/usr/bin/env python3
"""
For each location in a GeoJSON file: generate a short video and publish it to YouTube.
The youtube_url is written back into the GeoJSON feature's properties after each publish,
so the run is fully resumable (already-published features are skipped).

Usage:
  uv run python -m src.geojson_to_youtube locations.geojson
  uv run python -m src.geojson_to_youtube locations.geojson --output-dir output/yt
  uv run python -m src.geojson_to_youtube locations.geojson --music-dir mp3/
  uv run python -m src.geojson_to_youtube locations.geojson --limit 3
  uv run python -m src.geojson_to_youtube locations.geojson --dry-run
"""
import argparse
import json
import os
import random
import re
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from . import gmaps, video, youtube
from .main import make_description, make_title


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name).strip("_")


def _save_geojson(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: GOOGLE_MAPS_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Generate and publish a YouTube video for each location in a GeoJSON file"
    )
    parser.add_argument("geojson", help="Path to the GeoJSON file")
    parser.add_argument(
        "--output-dir", default="output/yt", metavar="DIR",
        help="Directory for generated MP4 files (default: output/yt)",
    )
    parser.add_argument(
        "--music-dir", default="mp3", metavar="DIR",
        help="Directory containing MP3 files to pick from randomly (default: mp3/)",
    )
    parser.add_argument(
        "--music-copyright", default="", metavar="TEXT",
        help="Music copyright notice appended to the YouTube description",
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Stop after publishing N videos (useful for smoke-testing)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Resolve places and check edge cases but do not generate videos or upload",
    )
    args = parser.parse_args()

    geojson_path = Path(args.geojson)
    if not geojson_path.exists():
        print(f"Error: GeoJSON file not found: {geojson_path}", file=sys.stderr)
        sys.exit(1)

    music_dir = Path(args.music_dir)
    mp3_files = sorted(music_dir.glob("*.mp3"))
    if not mp3_files:
        print(f"Warning: no MP3 files found in {music_dir}", file=sys.stderr)

    output_dir = Path(args.output_dir)
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    with open(geojson_path, encoding="utf-8") as f:
        geojson = json.load(f)

    features = geojson.get("features", [])
    total = len(features)
    print(f"Found {total} locations in {geojson_path.name}")

    yt_service = None
    if not args.dry_run:
        yt_service = youtube.authenticate()

    published = skipped = errors = 0

    with gmaps._client(api_key) as client:
        for i, feature in enumerate(features, start=1):
            if args.limit is not None and published >= args.limit:
                print(f"\nReached --limit {args.limit}, stopping.")
                break

            props = feature.get("properties", {})
            name = props.get("name", f"location_{i}")
            address = props.get("address", "")
            category = props.get("category", "")
            website_url = props.get("url", "")
            prefix = f"[{i}/{total}] {name}"

            if props.get("youtube_url"):
                print(f"{prefix} — already published, skipping")
                skipped += 1
                continue

            # ── resolve place ──────────────────────────────────────────────
            try:
                place_id = gmaps.search_place_by_name(f"{name} {address}", client)
                details = gmaps.get_place_details(place_id, client)
            except Exception as exc:
                print(f"{prefix} — SKIP (place not found: {exc})")
                skipped += 1
                continue

            # ── edge-case checks ───────────────────────────────────────────
            raw_photos = details.get("photos", [])
            if len(raw_photos) < 5:
                print(f"{prefix} — SKIP (only {len(raw_photos)} photo(s), need ≥ 5)")
                skipped += 1
                continue

            reviews = gmaps.select_best_reviews(details.get("reviews", []), count=1)
            if not reviews:
                print(f"{prefix} — SKIP (no qualifying reviews)")
                skipped += 1
                continue

            # ── collect metadata ───────────────────────────────────────────
            business_name = details.get("displayName", {}).get("text", name)
            rating = details.get("rating", 0.0)
            review_count = details.get("userRatingCount", 0)
            city, country, country_code = gmaps.get_location(details, client)
            loc = details.get("location", {})
            lat = loc.get("latitude")
            lng = loc.get("longitude")
            if lat is None or lng is None:
                geom_coords = (feature.get("geometry") or {}).get("coordinates")
                if geom_coords and len(geom_coords) >= 2:
                    lng, lat = geom_coords[0], geom_coords[1]
            maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
            api_website = details.get("websiteUri", website_url)

            print(
                f"{prefix} — {rating}★  {len(raw_photos)} photos  "
                f"{review_count} reviews  place_id={place_id}"
            )

            if args.dry_run:
                print(f"{prefix} — [dry-run] would generate & publish")
                skipped += 1
                continue

            # ── download first 5 photos ────────────────────────────────────
            out_path = output_dir / f"{_safe_filename(name)}.mp4"
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    photo_paths = gmaps.download_photos(
                        raw_photos, client, tmpdir, max_photos=5
                    )

                    music_path = str(random.choice(mp3_files)) if mp3_files else None

                    video.build_video(
                        business_name=business_name,
                        rating=rating,
                        photo_paths=photo_paths,
                        reviews=reviews,
                        website_url=api_website,
                        music_path=music_path,
                        output_path=str(out_path),
                        maps_url=maps_url,
                        city=city,
                        country=country,
                        country_code=country_code,
                        lat=lat,
                        lng=lng,
                    )

                    title = make_title(business_name, rating, category)
                    description = make_description(
                        business_name, rating, maps_url, api_website, category,
                        music_copyright=args.music_copyright,
                    )
                    yt_url = youtube.upload_video(
                        yt_service, str(out_path),
                        title=title, description=description,
                        lat=lat, lng=lng, location_description=business_name,
                    )

            except Exception as exc:
                print(f"{prefix} — ERROR: {exc}")
                errors += 1
                continue

            # ── update geojson immediately ─────────────────────────────────
            props["youtube_url"] = yt_url
            _save_geojson(geojson_path, geojson)

            published += 1
            print(f"{prefix} — Published → {yt_url}")

    print(f"\nDone — {published} published, {skipped} skipped, {errors} errors")


if __name__ == "__main__":
    main()
