#!/usr/bin/env python3
"""
Generate a 15s Manim companion video for a Google Maps place.

Tells a historical/contextual story arc: Hook → Key fact → Stat → CTA.
Accent color is derived from the place's dominant photo.

Usage:
  uv run python -m src.companion "https://maps.google.com/..."
  uv run python -m src.companion "https://..." --output output/companion.mp4
  uv run python -m src.companion "https://..." --handle "@MyChannel" --publish
  uv run python -m src.companion "https://..." --ollama  # force local model
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image

from . import gmaps, youtube


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------

_WIKI_HEADERS = {
    "User-Agent": "gmaps-reviews-short-video/1.0 (https://github.com/; girard.davila@gmail.com)"
}


def fetch_wikipedia_by_url(wiki_url: str) -> dict | None:
    """Fetch a Wikipedia article's full text from its URL (any language).

    Uses the MediaWiki action API with prop=extracts to get the complete
    article body, not just the intro paragraph returned by the REST summary.
    """
    import urllib.parse
    m = re.match(r"https?://([a-z]+)\.wikipedia\.org/wiki/(.+)", wiki_url)
    if not m:
        return None
    lang, raw_title = m.group(1), m.group(2)
    title = urllib.parse.unquote(raw_title)
    resp = httpx.get(
        f"https://{lang}.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "prop": "extracts",
            "titles": title,
            "explaintext": "true",   # plain text, no HTML
            "exsectionformat": "plain",
            "format": "json",
        },
        headers=_WIKI_HEADERS,
        timeout=15,
    )
    if not resp.is_success:
        return None
    pages = resp.json().get("query", {}).get("pages", {})
    page = next(iter(pages.values()))
    extract = page.get("extract", "")
    if not extract:
        return None
    return {"title": page.get("title", title), "extract": extract, "_lang": lang}


def _wiki_search_title(query: str) -> str | None:
    """Return the best-matching Wikipedia article title for a query."""
    resp = httpx.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 1,
        },
        headers=_WIKI_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("query", {}).get("search", [])
    return results[0]["title"] if results else None


def fetch_wikipedia(place_name: str, city: str = "", country: str = "") -> dict | None:
    """Return Wikipedia REST summary dict or None if not found.

    Performs a basic relevance check: if the returned article title shares no
    significant word with place_name, the result is discarded and None is
    returned, preventing false matches (e.g. "Plataforma Norte" → airport).
    """
    query = place_name
    if city:
        query += f" {city}"
    if country:
        query += f" {country}"

    print(f"  Wikipedia search: {query!r}")
    title = _wiki_search_title(query)
    if not title:
        print("  Wikipedia: no results")
        return None

    # Relevance guard: at least one non-trivial word from place_name must
    # appear in the returned title (case-insensitive).
    _stop = {"de", "la", "el", "the", "of", "in", "at", "and", "a", "an"}
    name_words = {
        w.lower() for w in re.split(r"\W+", place_name) if len(w) > 2 and w.lower() not in _stop
    }
    title_lower = title.lower()
    if name_words and not any(w in title_lower for w in name_words):
        print(f"  Wikipedia: rejected {title!r} (no overlap with {name_words})")
        return None

    resp = httpx.get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{httpx.URL(title)}",
        headers=_WIKI_HEADERS,
        timeout=10,
        follow_redirects=True,
    )
    if not resp.is_success:
        return None
    return resp.json()


# ---------------------------------------------------------------------------
# Dominant color extraction
# ---------------------------------------------------------------------------

def extract_dominant_color(photo_path: str) -> str:
    """Return hex accent color derived from the photo's dominant mid-tone."""
    img = Image.open(photo_path).convert("RGB").resize((60, 60))
    pixels = list(img.getdata())
    # Keep mid-tone, saturated pixels (avoid black/white/grey)
    filtered = [
        p for p in pixels
        if 80 < sum(p) < 650 and max(p) - min(p) > 40
    ]
    if not filtered:
        return "#D4A843"  # warm gold fallback
    r = sum(p[0] for p in filtered) // len(filtered)
    g = sum(p[1] for p in filtered) // len(filtered)
    b = sum(p[2] for p in filtered) // len(filtered)
    # Boost saturation: push the dominant channel higher
    mx = max(r, g, b)
    scale = min(255 / mx, 1.4) if mx > 0 else 1.0
    r = min(255, int(r * scale))
    g = min(255, int(g * scale))
    b = min(255, int(b * scale))
    return f"#{r:02X}{g:02X}{b:02X}"


# ---------------------------------------------------------------------------
# LLM story beat extraction
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """\
You are writing story beats for a 15-second vertical short video about a place.
The video has 4 scenes: Hook, Key Fact, Stat, CTA.

Place: {name}
Rating: {rating} / 5
Wikipedia extract:
\"\"\"
{wiki}
\"\"\"

Output ONLY valid JSON with exactly these fields:
{{
  "hook_subtitle": "<founding year or era + city, max 8 words>",
  "key_fact": "<one compelling historical or contextual fact, max 22 words>",
  "stat": {{
    "value": <integer — a notable number about this place>,
    "unit": "<unit label, max 4 words, e.g. 'visitors / year'>",
    "label": "<what this stat represents, max 5 words>"
  }},
  "cta": "<call-to-action phrase, max 6 words, e.g. 'Watch our full review'>"
}}

Rules:
- hook_subtitle: prefer founding year if known, otherwise era ("Medieval", "19th century")
- key_fact: surprising or evocative, not generic ("built in France")
- stat value: pick the most impressive number available (age, visitors, height, size)
- stat value must be a plain integer with no commas or units embedded
- cta: direct, warm, short
"""


def _build_wiki_text(
    wiki_data: dict | None,
    fallback_wiki: dict | None,
    place_name: str,
    rating: float,
) -> str:
    """Combine specific + fallback Wikipedia extracts into a single context string."""
    parts: list[str] = []
    if wiki_data and wiki_data.get("extract"):
        parts.append(wiki_data["extract"])
    if fallback_wiki and fallback_wiki.get("extract"):
        lang = fallback_wiki.get("_lang", "en")
        title = fallback_wiki.get("title", "parent site")
        parts.append(f"[{lang.upper()} Wikipedia — {title}]\n{fallback_wiki['extract']}")
    if not parts:
        return f"A place called {place_name} rated {rating} stars."
    return "\n\n".join(parts)


def extract_story_beats_claude(
    wiki_data: dict | None,
    place_data: dict,
    fallback_wiki: dict | None = None,
) -> dict:
    import anthropic

    wiki_text = _build_wiki_text(
        wiki_data, fallback_wiki,
        place_data["business_name"], place_data["rating"],
    )
    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system="You are a concise JSON extractor. Output only valid JSON, no markdown fences.",
        messages=[
            {
                "role": "user",
                "content": _EXTRACTION_PROMPT.format(
                    name=place_data["business_name"],
                    rating=place_data["rating"],
                    wiki=wiki_text[:4000],
                ),
            }
        ],
    )
    return json.loads(message.content[0].text)


def extract_story_beats_local(
    wiki_data: dict | None,
    place_data: dict,
    base_url: str = "http://localhost:8080",
    fallback_wiki: dict | None = None,
) -> dict:
    """Call a llama-server (or any OpenAI-compatible local server) for story beats."""
    wiki_text = _build_wiki_text(
        wiki_data, fallback_wiki,
        place_data["business_name"], place_data["rating"],
    )
    prompt = _EXTRACTION_PROMPT.format(
        name=place_data["business_name"],
        rating=place_data["rating"],
        wiki=wiki_text[:4000],
    )
    resp = httpx.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        json={
            "messages": [
                {
                    "role": "system",
                    "content": "You are a concise JSON extractor. Output only valid JSON, no markdown fences.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


def extract_story_beats(
    wiki_data: dict | None,
    place_data: dict,
    use_local: bool = False,
    local_url: str = "http://localhost:8080",
    fallback_wiki: dict | None = None,
) -> dict:
    if use_local:
        return extract_story_beats_local(
            wiki_data, place_data, base_url=local_url, fallback_wiki=fallback_wiki
        )
    try:
        return extract_story_beats_claude(wiki_data, place_data, fallback_wiki=fallback_wiki)
    except Exception as e:
        print(f"  Claude failed ({e}), falling back to local LLM at {local_url}...", file=sys.stderr)
        return extract_story_beats_local(
            wiki_data, place_data, base_url=local_url, fallback_wiki=fallback_wiki
        )


# ---------------------------------------------------------------------------
# Manim script generation
# ---------------------------------------------------------------------------

# Static scene body — raw string so curly braces are literal Python.
_MANIM_BODY = r'''
import textwrap
import os


class Scene1_Hook(Scene):
    def construct(self):
        self.camera.background_color = BG
        if PHOTO_PATH and os.path.exists(PHOTO_PATH):
            bg = ImageMobject(PHOTO_PATH)
            bg.set_height(config.frame_height)
            if bg.width < config.frame_width:
                bg.set_width(config.frame_width)
            bg.set_opacity(0.22)
            self.add(bg)
        name = Text(PLACE_NAME, font_size=48, color=ACCENT, weight=BOLD, font=MONO)
        name.move_to(UP * 0.6)
        sub = Text(HOOK_SUBTITLE, font_size=24, color=DIM, font=MONO)
        sub.next_to(name, DOWN, buff=0.4)
        self.play(Write(name), run_time=1.5)
        self.wait(0.3)
        self.play(FadeIn(sub), run_time=0.8)
        self.wait(1.0)
        self.play(FadeOut(Group(*self.mobjects)), run_time=0.4)


class Scene2_KeyFact(Scene):
    def construct(self):
        self.camera.background_color = BG
        lines = textwrap.wrap(KEY_FACT, 26)
        objs = [Text(l, font_size=38, color=WHITE, font=MONO) for l in lines]
        fact_group = VGroup(*objs).arrange(DOWN, buff=0.25)
        fact_group.move_to(ORIGIN)
        bar = Rectangle(
            width=0.12,
            height=fact_group.height + 0.5,
            color=ACCENT,
            fill_color=ACCENT,
            fill_opacity=1,
        )
        bar.next_to(fact_group, LEFT, buff=0.3)
        self.play(FadeIn(bar), Write(fact_group), run_time=2.0)
        self.wait(2.0)
        self.play(FadeOut(Group(*self.mobjects)), run_time=0.5)


class Scene3_Stat(Scene):
    def construct(self):
        self.camera.background_color = BG
        tracker = ValueTracker(0)
        number = always_redraw(
            lambda: Text(
                f"{int(tracker.get_value()):,}",
                font_size=72,
                color=ACCENT,
                weight=BOLD,
                font=MONO,
            ).move_to(UP * 0.5)
        )
        unit = Text(STAT_UNIT, font_size=28, color=DIM, font=MONO).move_to(DOWN * 0.5)
        label = Text(STAT_LABEL, font_size=22, color=WHITE, font=MONO).move_to(DOWN * 1.3)
        self.add(number, unit, label)
        self.play(
            tracker.animate.set_value(STAT_VALUE),
            run_time=2.0,
            rate_func=rush_from,
        )
        self.wait(0.5)
        self.play(FadeOut(Group(*self.mobjects)), run_time=0.5)


class Scene4_CTA(Scene):
    def construct(self):
        self.camera.background_color = BG
        stars_str = "★" * STAR_COUNT + "☆" * (5 - STAR_COUNT)
        stars = Text(stars_str, font_size=52, color=ACCENT, font=MONO)
        stars.move_to(UP * 2.0)
        rating_label = Text(RATING_STR, font_size=36, color=WHITE, font=MONO)
        rating_label.next_to(stars, DOWN, buff=0.3)
        cta_text = Text(CTA, font_size=30, color=DIM, font=MONO)
        cta_text.move_to(DOWN * 0.2)
        handle_text = Text(HANDLE, font_size=28, color=ACCENT, font=MONO)
        handle_text.next_to(cta_text, DOWN, buff=0.4)
        self.play(FadeIn(stars), run_time=0.6)
        self.play(FadeIn(rating_label), run_time=0.4)
        self.wait(0.2)
        self.play(Write(cta_text), run_time=0.8)
        self.play(FadeIn(handle_text), run_time=0.5)
        self.wait(0.5)
        self.play(FadeOut(Group(*self.mobjects)), run_time=0.4)
'''


def generate_manim_script(
    place_name: str,
    beats: dict,
    accent: str,
    rating: float,
    handle: str,
    output_dir: Path,
    photo_path: str | None = None,
) -> Path:
    import shutil

    star_count = min(5, max(0, round(rating)))
    stat = beats["stat"]
    stat_value = int(stat["value"]) if isinstance(stat["value"], (int, float)) else 0

    # Copy photo into work_dir so it persists for the duration of the render
    local_photo: str = ""
    if photo_path and Path(photo_path).exists():
        dest = output_dir / ("photo" + Path(photo_path).suffix)
        shutil.copy2(photo_path, dest)
        local_photo = str(dest)

    header = f"""\
from manim import *

config.pixel_width = 1080
config.pixel_height = 1920
config.frame_rate = 30

BG = "#1C1C1C"
ACCENT = {accent!r}
WHITE = "#EAEAEA"
DIM = "#888888"
MONO = "DejaVu Sans Mono"

PHOTO_PATH = {local_photo!r}
PLACE_NAME = {place_name!r}
HOOK_SUBTITLE = {beats['hook_subtitle']!r}
KEY_FACT = {beats['key_fact']!r}
STAT_VALUE = {stat_value}
STAT_UNIT = {stat['unit']!r}
STAT_LABEL = {stat['label']!r}
STAR_COUNT = {star_count}
RATING_STR = {f"{rating:.1f}"!r}
CTA = {beats['cta']!r}
HANDLE = {handle!r}
"""
    script_path = output_dir / "companion_script.py"
    script_path.write_text(header + _MANIM_BODY, encoding="utf-8")
    return script_path


# ---------------------------------------------------------------------------
# Render + stitch
# ---------------------------------------------------------------------------

_SCENES = [
    "Scene1_Hook",
    "Scene2_KeyFact",
    "Scene3_Stat",
    "Scene4_CTA",
]


def render_scenes(script_path: Path, quality: str = "l") -> list[Path]:
    """Render all 4 scenes and return paths to the generated mp4 files."""
    cmd = [
        sys.executable, "-m", "manim",
        f"-q{quality}",
        "--disable_caching",
        str(script_path),
        *_SCENES,
    ]
    subprocess.run(cmd, check=True, cwd=script_path.parent)

    media_dir = script_path.parent / "media" / "videos" / "companion_script"
    subdirs = [d for d in media_dir.iterdir() if d.is_dir()]
    if not subdirs:
        raise FileNotFoundError(f"No render output directory found under {media_dir}")
    res_dir = subdirs[0]

    paths = []
    for scene in _SCENES:
        p = res_dir / f"{scene}.mp4"
        if not p.exists():
            raise FileNotFoundError(f"Expected rendered scene not found: {p}")
        paths.append(p)
    return paths


def stitch_scenes(scene_paths: list[Path], output_path: Path) -> None:
    concat_txt = output_path.parent / "concat.txt"
    concat_txt.write_text(
        "\n".join(f"file '{p}'" for p in scene_paths),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_txt),
            "-c", "copy",
            str(output_path),
        ],
        check=True,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: GOOGLE_MAPS_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Generate a 15s Manim companion video for a Google Maps place"
    )
    parser.add_argument("url", help="Google Maps business URL")
    parser.add_argument(
        "--output", default=None,
        help="Output mp4 path (default: output/<slug>_companion_<ts>.mp4)",
    )
    parser.add_argument(
        "--handle", default=os.environ.get("YOUTUBE_HANDLE", "@ReviewReel"),
        help="YouTube channel handle shown in CTA (default: $YOUTUBE_HANDLE or @ReviewReel)",
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
        help="Upload companion video to YouTube after rendering",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        print("Fetching place data...")
        place_data = gmaps.resolve_url(args.url, api_key, photo_dir=tmpdir)
        name = place_data["business_name"]
        rating = place_data["rating"]
        print(f"  {name} — {rating}★")

        # Dominant color from first photo
        photo_paths = place_data.get("photo_paths", [])
        if photo_paths:
            accent = extract_dominant_color(photo_paths[0])
            print(f"  Accent color: {accent}")
        else:
            accent = "#D4A843"
            print("  No photos — using fallback accent color")

        print("Fetching Wikipedia context...")
        wiki = fetch_wikipedia(
            name,
            city=place_data.get("city", ""),
            country=place_data.get("country", ""),
        )
        if wiki:
            print(f"  Found: {wiki.get('title', '?')}")
        else:
            print("  No Wikipedia article found — generating from place data only")

        print("Extracting story beats...")
        beats = extract_story_beats(
            wiki, place_data,
            use_local=args.local,
            local_url=args.local_url,
        )
        print(f"  Hook:     {name} / {beats['hook_subtitle']}")
        print(f"  Key fact: {beats['key_fact']}")
        print(f"  Stat:     {beats['stat']['value']} {beats['stat']['unit']}")
        print(f"  CTA:      {beats['cta']}")

        # Output path
        if args.output is None:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("output", exist_ok=True)
            args.output = f"output/{slug}_companion_{ts}.mp4"

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tmpdir) / "manim"
        work_dir.mkdir()

        print("Generating Manim script...")
        script_path = generate_manim_script(
            place_name=name,
            beats=beats,
            accent=accent,
            rating=rating,
            handle=args.handle,
            output_dir=work_dir,
        )

        print(f"Rendering scenes (quality={args.quality})...")
        scene_paths = render_scenes(script_path, quality=args.quality)
        print(f"  Rendered {len(scene_paths)} scenes")

        print("Stitching...")
        stitch_scenes(scene_paths, output_path)
        print(f"  Output: {output_path}")

        if args.publish:
            print("Publishing to YouTube...")
            service = youtube.authenticate()
            title = f"{name} — Did You Know? 🏛️"
            description = (
                f"A 15-second historical companion video for {name}.\n\n"
                f"{beats['key_fact']}\n\n"
                f"Watch our full review: {args.handle}"
            )
            url = youtube.upload_video(
                service,
                str(output_path),
                title=title,
                description=description,
                lat=place_data.get("lat"),
                lng=place_data.get("lng"),
                location_description=place_data.get("city", ""),
            )
            print(f"  Published: {url}")


if __name__ == "__main__":
    main()
