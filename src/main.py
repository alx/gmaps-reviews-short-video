#!/usr/bin/env python3
"""
Generate a 7-second short video from a Google Maps business URL.

Usage:
  uv run gmaps-reviews-short-video "https://www.google.com/maps/place/..."
  uv run python -m src.main "https://..." --output output/my_video.mp4
  uv run python -m src.main "https://..." --music mp3/track.mp3
"""
import argparse
import os
import sys
import tempfile

from dotenv import load_dotenv

from . import gmaps
from . import video


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
        "--output", default="output/output.mp4", help="Output file path (default: output/output.mp4)"
    )
    parser.add_argument(
        "--music", metavar="FILE",
        help="Path to a local MP3/WAV file to use as background music.",
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

        print("Generating video...")
        video.build_video(
            business_name=place_data["business_name"],
            rating=place_data["rating"],
            photo_paths=place_data["photo_paths"],
            reviews=place_data["reviews"],
            output_path=args.output,
            website_url=place_data.get("website_url", ""),
            music_path=args.music,
        )

    print(f"Done → {args.output}")


if __name__ == "__main__":
    main()
