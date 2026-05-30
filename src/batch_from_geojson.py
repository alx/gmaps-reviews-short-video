#!/usr/bin/env python3
"""
Generate a short video for each location in a GeoJSON file.

Usage:
  uv run python -m src.batch_from_geojson locations.geojson
  uv run python -m src.batch_from_geojson locations.geojson --output-dir output/toulouse
  uv run python -m src.batch_from_geojson locations.geojson --music mp3/track.mp3
  uv run python -m src.batch_from_geojson locations.geojson --music mp3/track.mp3 --publish
"""
import argparse
import csv
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from . import gmaps, video, youtube


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name).strip("_")


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: GOOGLE_MAPS_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Batch-generate short videos from a GeoJSON locations file"
    )
    parser.add_argument("geojson", help="Path to the GeoJSON file")
    parser.add_argument(
        "--output-dir",
        default="output/batch",
        metavar="DIR",
        help="Directory for output videos and CSV (default: output/batch)",
    )
    parser.add_argument(
        "--music",
        metavar="FILE",
        help="Path to a local MP3/WAV file to use as background music",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Upload each generated video to YouTube after generation.",
    )
    args = parser.parse_args()

    geojson_path = Path(args.geojson)
    if not geojson_path.exists():
        print(f"Error: GeoJSON file not found: {geojson_path}", file=sys.stderr)
        sys.exit(1)

    if args.music and not os.path.exists(args.music):
        print(f"Error: music file not found: {args.music}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(geojson_path) as f:
        geojson = json.load(f)

    features = geojson.get("features", [])
    total = len(features)
    print(f"Found {total} locations in {geojson_path.name}")

    yt_service = youtube.authenticate() if args.publish else None

    rows: list[dict] = []

    with gmaps._client(api_key) as client:
        for i, feature in enumerate(features, start=1):
            props = feature.get("properties", {})
            name = props.get("name", f"location_{i}")
            category = props.get("category", "")
            address = props.get("address", "")
            phone = props.get("phone", "")
            geojson_url = props.get("url", "")

            output_path = output_dir / f"{_safe_filename(name)}.mp4"

            row: dict = {
                "name": name,
                "category": category,
                "address": address,
                "phone": phone,
                "geojson_url": geojson_url,
                "place_id": "",
                "rating": "",
                "review_count": "",
                "photo_count": "",
                "reviews_used": "",
                "website_url": "",
                "output_path": str(output_path),
                "youtube_url": "",
                "status": "",
                "error": "",
            }

            prefix = f"[{i}/{total}] {name}"

            if output_path.exists():
                print(f"{prefix} — skipped (already exists)")
                row["status"] = "skipped"
                rows.append(row)
                continue

            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    place_id = gmaps.search_place_by_name(f"{name} {address}", client)
                    row["place_id"] = place_id

                    details = gmaps.get_place_details(place_id, client)

                    business_name = details.get("displayName", {}).get("text", name)
                    rating = details.get("rating", 0.0)
                    review_count = details.get("userRatingCount", 0)
                    website_url = details.get("websiteUri", "")

                    raw_photos = details.get("photos", [])
                    photo_paths = gmaps.download_photos(raw_photos, client, tmpdir)
                    reviews = gmaps.select_best_reviews(details.get("reviews", []))

                    row.update(
                        {
                            "rating": rating,
                            "review_count": review_count,
                            "photo_count": len(photo_paths),
                            "reviews_used": len(reviews),
                            "website_url": website_url,
                        }
                    )

                    video.build_video(
                        business_name=business_name,
                        rating=rating,
                        photo_paths=photo_paths,
                        reviews=reviews,
                        website_url=website_url,
                        music_path=args.music,
                        output_path=str(output_path),
                    )

                row["status"] = "success"
                print(f"{prefix} — OK  ({rating}★, {len(photo_paths)} photos, {len(reviews)} reviews)")

                if yt_service is not None:
                    website_section = f"\n\n🌐 WEBSITE\n{website_url}" if website_url else ""
                    description = (
                        f"{business_name} — Google Maps Reviews\n\n"
                        f"⭐ {rating} / 5.0  •  {review_count} reviews\n\n"
                        f"📍 GOOGLE MAPS\n{geojson_url}"
                        f"{website_section}\n\n"
                        "---\n"
                        "SHORT VIDEO GENERATED BY REVIEWREEL\n"
                        "This video was automatically created from public Google Maps data.\n\n"
                        "---\n"
                        "OPEN SOURCE\n"
                        "https://github.com/alx/gmaps-reviews-short-video"
                    )
                    yt_url = youtube.upload_video(
                        yt_service,
                        str(output_path),
                        title=f"{business_name} — Google Maps Reviews",
                        description=description,
                    )
                    row["youtube_url"] = yt_url
                    print(f"{prefix} — Published → {yt_url}")

            except Exception as exc:
                row["status"] = "error"
                row["error"] = str(exc)
                print(f"{prefix} — ERROR: {exc}")

            rows.append(row)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"results_{timestamp}.csv"
    fieldnames = [
        "name", "category", "address", "phone", "geojson_url",
        "place_id", "rating", "review_count", "photo_count", "reviews_used",
        "website_url", "output_path", "youtube_url", "status", "error",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    success = sum(1 for r in rows if r["status"] == "success")
    skipped = sum(1 for r in rows if r["status"] == "skipped")
    errors = sum(1 for r in rows if r["status"] == "error")
    print(f"\nDone — {success} generated, {skipped} skipped, {errors} errors")
    print(f"CSV  → {csv_path}")


if __name__ == "__main__":
    main()
