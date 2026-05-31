#!/usr/bin/env python3
"""
Generate a short video from a Google Maps business URL.

Usage:
  uv run gmaps-reviews-short-video "https://www.google.com/maps/place/..."
  uv run python -m src.main "https://..." --output output/my_video.mp4
  uv run python -m src.main "https://..." --music mp3/track.mp3 --publish
"""
import argparse
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from . import gmaps
from . import video
from . import youtube

RATING_HOOKS = {
    5: ("🌟", "Must Visit"),
    4: ("⭐", "Locals Love"),
    3: ("📍", "Worth Knowing"),
}


def load_hashtag_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "hashtags.json"
    try:
        with open(config_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"default": ["#GoogleMaps", "#LocalBusiness", "#MustVisit", "#ShortVideo"]}


def make_title(business_name: str, rating: float, category: str = "") -> str:
    stars = round(rating)
    emoji, hook = RATING_HOOKS.get(stars, ("📍", "Check Out"))
    base = f"{emoji} {hook} – {business_name}"
    if len(base) <= 50:
        return base
    max_name = 50 - len(f"{emoji} {hook} – ") - 1
    return f"{emoji} {hook} – {business_name[:max_name]}…"


def make_description(
    business_name: str,
    rating: float,
    maps_url: str,
    website_url: str = "",
    category: str = "",
    music_copyright: str = "",
) -> str:
    context = (
        f"Discover what people are saying about {business_name}, "
        f"rated ⭐ {rating}/5 on Google Maps."
    )
    cta = f"📍 Find them on Google Maps:\n{maps_url}"
    if website_url:
        cta += f"\n\n🌐 {website_url}"
    tag_config = load_hashtag_config()
    slug = category.replace(" ", "").lower() if category else ""
    tags = tag_config.get("overrides", {}).get(slug) or tag_config.get("default", [])
    hashtags = "  ".join(tags)
    desc = f"{context}\n\n{cta}\n\n{hashtags}"
    if music_copyright:
        desc += f"\n\n🎵 {music_copyright}"
    return desc


def _used_review_texts(output_dir: str, business_name: str) -> set[str]:
    """Return review texts already written to JSON sidecars in output_dir for this business."""
    used: set[str] = set()
    try:
        paths = Path(output_dir).glob("*.json")
    except (OSError, ValueError):
        return used
    for json_path in paths:
        try:
            with open(json_path, encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if meta.get("business_name") != business_name:
            continue
        text = (meta.get("review") or {}).get("text", "")
        if text:
            used.add(text)
    return used


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: GOOGLE_MAPS_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Generate a short video from a Google Maps business URL"
    )
    parser.add_argument("url", help="Google Maps business URL")
    parser.add_argument(
        "--output", default=None,
        help="Output file path (default: output/<slug>_<timestamp>.mp4)",
    )
    parser.add_argument(
        "--music", metavar="FILE",
        help="Path to a local MP3/WAV file to use as background music.",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="Upload the generated video to YouTube (ReviewReel channel) after generation.",
    )
    parser.add_argument(
        "--music-copyright", metavar="TEXT", default="",
        help="Music copyright notice appended to the YouTube description.",
    )
    args = parser.parse_args()

    if args.music and not os.path.exists(args.music):
        print(f"Error: music file not found: {args.music}", file=sys.stderr)
        sys.exit(1)

    print("Fetching place data...")
    with tempfile.TemporaryDirectory() as tmpdir:
        place_data = gmaps.resolve_url(args.url, api_key, photo_dir=tmpdir)
        print(f"  Business:  {place_data['business_name']}")
        print(f"  Rating:    {place_data['rating']} ({place_data['review_count']} reviews)")
        print(f"  Photos:    {len(place_data['photo_paths'])}")
        print(f"  Reviews:   {len(place_data['reviews'])}")

        if args.output is None:
            slug = re.sub(r"[^a-z0-9]+", "-", place_data["business_name"].lower()).strip("-")
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("output", exist_ok=True)
            args.output = f"output/{slug}_{ts}.mp4"

        print("Generating video...")
        stem, ext = os.path.splitext(args.output)
        all_reviews = place_data["reviews"]
        used_texts = _used_review_texts(
            os.path.dirname(os.path.abspath(args.output)),
            place_data["business_name"],
        )
        fresh = [r for r in all_reviews if r.get("text") not in used_texts]
        reviews = (fresh or all_reviews)[:5] or [{}]
        if used_texts and fresh:
            print(f"  Skipping {len(used_texts)} already-used review(s), {len(fresh)} fresh.")
        output_paths = []
        for i, review in enumerate(reviews):
            out = f"{stem}_{i + 1}{ext}" if len(reviews) > 1 else args.output
            music_offset = i * (video.TOTAL + 2)
            video.build_video(
                business_name=place_data["business_name"],
                rating=place_data["rating"],
                photo_paths=place_data["photo_paths"],
                reviews=[review] if review else [],
                output_path=out,
                website_url=place_data.get("website_url", ""),
                music_path=args.music,
                maps_url=args.url,
                music_offset=music_offset,
            )
            metadata = {
                "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "maps_url": args.url,
                "business_name": place_data["business_name"],
                "rating": place_data["rating"],
                "review_count": place_data["review_count"],
                "website_url": place_data.get("website_url", ""),
                "review": review or None,
                "review_index": i,
                "photo_count": len(place_data["photo_paths"]),
                "music": args.music,
                "output_video": out,
            }
            json_path = os.path.splitext(out)[0] + ".json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            output_paths.append(out)

    print(f"Done → {', '.join(output_paths)}")

    if args.publish:
        business_name = place_data["business_name"]
        rating = place_data["rating"]
        website_url = place_data.get("website_url", "")
        title = make_title(business_name, rating)
        description = make_description(business_name, rating, args.url, website_url, music_copyright=args.music_copyright)

        print("Uploading to YouTube...")
        service = youtube.authenticate()
        for out in output_paths:
            yt_url = youtube.upload_video(service, out, title=title, description=description)
            print(f"Published → {yt_url}")
            json_path = os.path.splitext(out)[0] + ".json"
            try:
                with open(json_path, encoding="utf-8") as f:
                    meta = json.load(f)
                meta["youtube_url"] = yt_url
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
            except OSError:
                pass


if __name__ == "__main__":
    main()
