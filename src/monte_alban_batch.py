#!/usr/bin/env python3
"""
Discover all Monte Albán sites on Google Maps and generate a companion video
for each one.

Discovery strategy:
  1. searchText "Monte Albán Oaxaca" → anchor coordinates of the main site
  2. searchNearby within 2 km → all sub-sites with their own Maps listings
  3. Deduplicate by place_id

For each discovered place:
  - Wikipedia + Claude/Ollama → story beats
  - Manim renders a 15s vertical companion video
  - Optional --publish to YouTube

Usage:
  uv run python -m src.monte_alban_batch
  uv run python -m src.monte_alban_batch --output-dir output/monte_alban
  uv run python -m src.monte_alban_batch --quality h --publish
  uv run python -m src.monte_alban_batch --ollama
  uv run python -m src.monte_alban_batch --dry-run   # list sites only, no rendering
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

import httpx
from dotenv import load_dotenv

from . import gmaps, youtube
from .companion import (
    fetch_wikipedia_by_url,
    extract_dominant_color,
    extract_story_beats,
    fetch_wikipedia,
    generate_manim_script,
    render_scenes,
    stitch_scenes,
)

# Monte Albán main site anchor — used as fallback if searchText finds nothing
_MONTE_ALBAN_LAT = 17.0435
_MONTE_ALBAN_LNG = -96.7672
_SEARCH_RADIUS_M = 2500

# Place types that represent distinct sub-sites or attractions within an
# archaeological zone. Broad enough to catch all named structures.
_INCLUDED_TYPES = [
    "tourist_attraction",
    "historical_landmark",
    "museum",
    "cultural_landmark",
    "monument",
    "archaeological_site",
    "point_of_interest",
]

_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.rating,"
    "places.userRatingCount,"
    "places.location,"
    "places.formattedAddress,"
    "places.photos,"
    "places.reviews,"
    "places.websiteUri,"
    "places.types"
)


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name).strip("_")


def discover_sites(client: httpx.Client) -> list[dict]:
    """Return deduplicated list of Places API place dicts for Monte Albán sites."""
    seen: set[str] = set()
    places: list[dict] = []

    # Step 1: anchor the main site
    anchor_lat, anchor_lng = _MONTE_ALBAN_LAT, _MONTE_ALBAN_LNG
    resp = client.post(
        f"{gmaps.BASE_URL}/places:searchText",
        json={"textQuery": "Monte Albán archaeological zone Oaxaca Mexico"},
        headers={"X-Goog-FieldMask": "places.id,places.displayName,places.location"},
    )
    if resp.is_success:
        results = resp.json().get("places", [])
        if results:
            loc = results[0].get("location", {})
            anchor_lat = loc.get("latitude", anchor_lat)
            anchor_lng = loc.get("longitude", anchor_lng)
            print(f"  Anchor: {results[0].get('displayName', {}).get('text', '?')} "
                  f"({anchor_lat:.4f}, {anchor_lng:.4f})")

    # Step 2: nearby search for all sub-sites
    resp = client.post(
        f"{gmaps.BASE_URL}/places:searchNearby",
        json={
            "includedTypes": _INCLUDED_TYPES,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": anchor_lat, "longitude": anchor_lng},
                    "radius": _SEARCH_RADIUS_M,
                }
            },
            "maxResultCount": 20,
        },
        headers={"X-Goog-FieldMask": _FIELD_MASK},
    )
    if resp.is_success:
        for p in resp.json().get("places", []):
            pid = p.get("id", "")
            if pid and pid not in seen:
                seen.add(pid)
                places.append(p)

    # Step 3: targeted text searches for known named structures that may not
    # surface in a generic nearby search
    known_structures = [
        "Plataforma Norte Monte Albán",
        "Plataforma Sur Monte Albán",
        "Edificio J Monte Albán",
        "Juego de Pelota Monte Albán",
        "Museo del Sitio Monte Albán",
        "Danzantes Monte Albán",
    ]
    for query in known_structures:
        resp = client.post(
            f"{gmaps.BASE_URL}/places:searchText",
            json={"textQuery": query},
            headers={"X-Goog-FieldMask": _FIELD_MASK},
        )
        if resp.is_success:
            for p in resp.json().get("places", []):
                pid = p.get("id", "")
                if pid and pid not in seen:
                    # Only include if within 5 km of anchor (avoid false matches)
                    loc = p.get("location", {})
                    plat = loc.get("latitude", 0.0)
                    plng = loc.get("longitude", 0.0)
                    dist = ((plat - anchor_lat) ** 2 + (plng - anchor_lng) ** 2) ** 0.5
                    if dist < 0.05:  # ~5 km in degrees
                        seen.add(pid)
                        places.append(p)

    return places


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: GOOGLE_MAPS_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Discover Monte Albán sites and generate a companion video for each"
    )
    parser.add_argument(
        "--output-dir", default="output/monte_alban",
        metavar="DIR",
        help="Directory for output videos and CSV (default: output/monte_alban)",
    )
    parser.add_argument(
        "--handle", default=os.environ.get("YOUTUBE_HANDLE", "@ReviewReel"),
        help="YouTube channel handle shown in CTA",
    )
    parser.add_argument(
        "--quality", choices=["l", "m", "h"], default="l",
        help="Manim render quality: l=480p, m=720p, h=1080p (default: l)",
    )
    parser.add_argument(
        "--local", action="store_true",
        help="Force local LLM (llama-server / any OpenAI-compatible server) instead of Claude",
    )
    parser.add_argument(
        "--local-url", default="http://localhost:8080",
        help="Base URL of the local LLM server (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="Upload each companion video to YouTube after rendering",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Discover and list sites only — do not render videos",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    yt_service = youtube.authenticate() if args.publish else None

    print("Discovering Monte Albán sites...")
    with gmaps._client(api_key) as client:
        sites = discover_sites(client)

    if not sites:
        print("No sites found. Check API key and quota.", file=sys.stderr)
        sys.exit(1)

    print(f"\nFound {len(sites)} site(s):")
    for s in sites:
        name = s.get("displayName", {}).get("text", "?")
        rating = s.get("rating", "—")
        print(f"  • {name}  ({rating}★)")

    # Pre-fetch Monte Albán Wikipedia articles (EN + ES) once as shared fallback.
    # Sub-sites that have no dedicated Wikipedia article will draw context from here.
    print("\nFetching Monte Albán Wikipedia fallback articles...")
    _en = fetch_wikipedia_by_url("https://en.wikipedia.org/wiki/Monte_Alb%C3%A1n")
    _es = fetch_wikipedia_by_url("https://es.wikipedia.org/wiki/Monte_Alb%C3%A1n")
    if _en:
        print(f"  EN: {_en.get('title')} ({len(_en.get('extract', ''))} chars)")
    if _es:
        print(f"  ES: {_es.get('title')} ({len(_es.get('extract', ''))} chars)")
    # Merge EN + ES into a single fallback dict by concatenating their extracts
    if _en and _es:
        monte_alban_wiki: dict | None = dict(_en)
        monte_alban_wiki["extract"] = (
            _en.get("extract", "") + "\n\n[ES Wikipedia]\n" + _es.get("extract", "")
        )
    else:
        monte_alban_wiki = _en or _es

    if args.dry_run:
        # Write a discovery JSON for inspection
        discovery_path = output_dir / "sites.json"
        with open(discovery_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "id": s.get("id"),
                        "name": s.get("displayName", {}).get("text"),
                        "rating": s.get("rating"),
                        "address": s.get("formattedAddress"),
                        "location": s.get("location"),
                    }
                    for s in sites
                ],
                f, indent=2, ensure_ascii=False,
            )
        print(f"\nDry run — discovery saved to {discovery_path}")
        return

    rows: list[dict] = []
    total = len(sites)

    for i, place in enumerate(sites, start=1):
        place_id = place.get("id", "")
        name = place.get("displayName", {}).get("text", f"site_{i}")
        rating = place.get("rating", 0.0)
        loc = place.get("location", {})
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        city = "Oaxaca"
        country = "Mexico"
        address = place.get("formattedAddress", "")
        maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

        slug = _safe_filename(name.lower())
        output_path = output_dir / f"{slug}_companion.mp4"
        prefix = f"[{i}/{total}] {name}"

        row: dict = {
            "place_id": place_id,
            "name": name,
            "rating": rating,
            "address": address,
            "maps_url": maps_url,
            "output_path": str(output_path),
            "youtube_url": "",
            "status": "",
            "error": "",
        }

        if output_path.exists():
            print(f"{prefix} — skipped (already exists)")
            row["status"] = "skipped"
            rows.append(row)
            continue

        print(f"\n{prefix}")
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Photos from searchNearby are often absent for archaeological
                # sub-sites. Fall back to a full place details call if needed.
                raw_photos = place.get("photos", [])
                if not raw_photos:
                    with gmaps._client(api_key) as client:
                        details = gmaps.get_place_details(place_id, client)
                    raw_photos = details.get("photos", [])
                    print(f"  Photos via details fallback: {len(raw_photos)}")
                else:
                    print(f"  Photos from nearby search: {len(raw_photos)}")

                photo_paths: list[str] = []
                if raw_photos:
                    with gmaps._client(api_key) as client:
                        photo_paths = gmaps.download_photos(
                            raw_photos[:1], client, tmpdir, max_photos=1
                        )

                accent = (
                    extract_dominant_color(photo_paths[0])
                    if photo_paths
                    else "#D4A843"
                )
                print(f"  Accent: {accent}  Photo: {'yes' if photo_paths else 'none'}")

                print("  Fetching Wikipedia...")
                # Use "Monte Albán" as context so sub-site searches like
                # "Plataforma Norte Monte Albán" stay on-target, rather than
                # matching unrelated articles via generic city/country terms.
                wiki = fetch_wikipedia(name, city="Monte Albán")
                if wiki:
                    print(f"  Wikipedia: {wiki.get('title', '?')}")
                else:
                    print("  No Wikipedia article — generating from place data only")

                place_data = {
                    "business_name": name,
                    "rating": rating,
                    "city": city,
                    "country": country,
                    "lat": lat,
                    "lng": lng,
                }

                print("  Extracting story beats...")
                beats = extract_story_beats(
                    wiki, place_data,
                    use_local=args.local,
                    local_url=args.local_url,
                    fallback_wiki=monte_alban_wiki,
                )
                print(f"    Key fact: {beats['key_fact']}")
                print(f"    Stat: {beats['stat']['value']} {beats['stat']['unit']}")

                work_dir = Path(tmpdir) / "manim"
                work_dir.mkdir()

                script_path = generate_manim_script(
                    place_name=name,
                    beats=beats,
                    accent=accent,
                    rating=rating,
                    handle=args.handle,
                    output_dir=work_dir,
                    photo_path=photo_paths[0] if photo_paths else None,
                )

                print(f"  Rendering ({args.quality})...")
                scene_paths = render_scenes(script_path, quality=args.quality)
                stitch_scenes(scene_paths, output_path)
                print(f"  → {output_path}")

            row["status"] = "success"

            if yt_service is not None:
                title = f"{name} — Did You Know? 🏛️"
                description = (
                    f"{beats['key_fact']}\n\n"
                    f"Part of the Monte Albán archaeological zone, Oaxaca, Mexico.\n\n"
                    f"Watch our full review: {args.handle}"
                )
                yt_url = youtube.upload_video(
                    yt_service,
                    str(output_path),
                    title=title,
                    description=description,
                    lat=lat,
                    lng=lng,
                    location_description=name,
                )
                row["youtube_url"] = yt_url
                print(f"  Published → {yt_url}")

        except Exception as exc:
            row["status"] = "error"
            row["error"] = str(exc)
            print(f"  ERROR: {exc}")

        rows.append(row)

    # Write CSV summary
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"results_{timestamp}.csv"
    fieldnames = [
        "place_id", "name", "rating", "address",
        "maps_url", "output_path", "youtube_url", "status", "error",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    success = sum(1 for r in rows if r["status"] == "success")
    skipped = sum(1 for r in rows if r["status"] == "skipped")
    errors = sum(1 for r in rows if r["status"] == "error")
    print(f"\nDone — {success} rendered, {skipped} skipped, {errors} errors")
    print(f"CSV  → {csv_path}")


if __name__ == "__main__":
    main()
