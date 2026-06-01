#!/usr/bin/env python3
"""
Standalone video generation profiling script.

Runs build_video() on existing session photos (no API calls needed) and
prints a per-step timing table.  Designed to be wrapped with pyinstrument
for an HTML flamechart.

Usage
-----
# Step timing table only:
    uv run python scripts/profile_video.py

# HTML flamechart (opens in browser):
    uv run python -m pyinstrument --html -o profile.html scripts/profile_video.py
    xdg-open profile.html

# Deep encode analysis (frame gen vs ffmpeg, preset/fps/resolution comparison):
    uv run python scripts/profile_video.py --analyze

# Use specific photos:
    uv run python scripts/profile_video.py --photos /path/a.jpg /path/b.jpg

# Include map rendering (staticmap HTTP fetch):
    uv run python scripts/profile_video.py --map

# Include audio encoding:
    uv run python scripts/profile_video.py --music mp3/japan.mp3
"""

import argparse
import pathlib
import sys
import time

import numpy as np

# Ensure src/ is importable when running from the project root
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.video import build_video  # noqa: E402

# ---------------------------------------------------------------------------
# Sample business data — no API call required
# ---------------------------------------------------------------------------
SAMPLE_BUSINESS = "Le Bàcaro"
SAMPLE_RATING = 4.8
SAMPLE_REVIEWS = [
    {
        "author": "Marie D.",
        "rating": 5,
        "text": (
            "Excellent restaurant, accueil chaleureux et cuisine raffinée. "
            "Les pâtes fraîches sont un délice, à recommander absolument !"
        ),
        "relative_time_description": "il y a 2 semaines",
    }
]
SAMPLE_CITY = "Toulouse"
SAMPLE_COUNTRY = "France"
SAMPLE_COUNTRY_CODE = "FR"
SAMPLE_LAT = 43.6047
SAMPLE_LNG = 1.4442


def _find_photos_in_sessions(workspace: pathlib.Path) -> list[str]:
    """Return full-res photos from the most-recently-modified session."""
    sessions = sorted(
        [d for d in (workspace / "sessions").iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for session in sessions:
        photos_dir = session / "photos"
        jpgs = sorted(photos_dir.glob("*.jpg")) if photos_dir.exists() else []
        if jpgs:
            return [str(p) for p in jpgs]
        # Fall back to thumbs (smaller, faster for profiling)
        thumbs_dir = session / "thumbs"
        jpgs = sorted(thumbs_dir.glob("*.jpg")) if thumbs_dir.exists() else []
        if jpgs:
            print(f"  [profile] Using thumbnails from {session.name} (no full-res photos found)")
            return [str(p) for p in jpgs]
    return []


def _build_composite(photo_paths: list[str], include_map: bool, music_path: str | None):
    """Build the CompositeVideoClip without writing to disk — returns (clip, fps)."""
    import random
    from src import video as v

    fps = 30
    cfg = {}
    font_bold = v.find_font()
    font_reg = v.find_font_regular()

    n = min(len(photo_paths), 5)
    photos = random.sample(photo_paths, n)

    effective_total = v.TOTAL
    clip_dur = (effective_total + (n - 1) * v.CROSSFADE) / n

    from moviepy import AudioFileClip, CompositeVideoClip, ImageClip
    from moviepy import afx, vfx

    photo_clips = []
    for i, path in enumerate(photos):
        clip = v.make_ken_burns_clip(path, clip_dur)
        if i > 0:
            clip = clip.with_effects([vfx.CrossFadeIn(v.CROSSFADE)])
        clip = clip.with_start(i * (clip_dur - v.CROSSFADE))
        photo_clips.append(clip)

    title_clips = []
    tc = (
        v.make_title_card(SAMPLE_BUSINESS, SAMPLE_RATING, font_bold, font_reg,
                          photo_path=photos[0],
                          city=SAMPLE_CITY, country=SAMPLE_COUNTRY,
                          country_code=SAMPLE_COUNTRY_CODE)
        .with_duration(v.TITLE_DUR)
        .with_effects([vfx.FadeOut(v.CROSSFADE)])
        .with_start(0)
        .with_position("center")
    )
    title_clips.append(tc)

    review_start = v.TITLE_DUR - v.CROSSFADE
    review_end = effective_total - v.OUTRO_DUR
    review_dur = review_end - review_start
    rgb_arr, alpha_arr, card_h = v.make_review_card(SAMPLE_REVIEWS[0], font_reg, font_bold)
    card_clip = ImageClip(rgb_arr)
    mask_clip = ImageClip(alpha_arr, is_mask=True)
    card_clip = (
        card_clip
        .with_mask(mask_clip)
        .with_duration(review_dur)
        .with_effects([vfx.CrossFadeIn(v.CROSSFADE)])
        .with_start(review_start)
        .with_position((v.CARD_X, v.CARD_Y_BOT - card_h))
    )

    oc = (
        v.make_outro_card(SAMPLE_BUSINESS, "https://example.com", font_bold, font_reg,
                          "https://maps.google.com/?q=test",
                          city=SAMPLE_CITY, country=SAMPLE_COUNTRY,
                          country_code=SAMPLE_COUNTRY_CODE)
        .with_duration(v.OUTRO_DUR)
        .with_effects([vfx.CrossFadeIn(v.CROSSFADE)])
        .with_start(effective_total - v.OUTRO_DUR)
        .with_position("center")
    )

    all_clips = photo_clips + [card_clip] + title_clips + [oc]
    final = (
        CompositeVideoClip(all_clips, size=(v.W, v.H))
        .with_duration(effective_total)
        .with_effects([vfx.FadeIn(v.FADE), vfx.FadeOut(v.FADE)])
    )

    if music_path:
        audio = (
            AudioFileClip(music_path)
            .subclipped(0, effective_total)
            .with_effects([afx.AudioFadeIn(v.FADE), afx.AudioFadeOut(v.FADE)])
        )
        final = final.with_audio(audio)

    return final, fps


def analyze_encode(photo_paths: list[str], include_map: bool, music_path: str | None) -> None:
    """
    Break down the ffmpeg_encode step:
      1. Frame generation time (Python/numpy, no encoding)
      2. Encoding time across presets (ultrafast → medium)
      3. FPS comparison (24 vs 30)
    """
    print("\n══ Encode breakdown analysis ════════════════════════════════════")
    print("  Building composite clip...")
    final, fps = _build_composite(photo_paths, include_map, music_path)
    n_frames = int(final.duration * fps)
    raw_gb = n_frames * 1080 * 1920 * 3 / 1e9
    print(f"  Video: {final.duration:.1f}s  ×  {fps}fps  =  {n_frames} frames  ({raw_gb:.2f} GB raw)\n")

    # ── 1. Frame generation only (no ffmpeg) ─────────────────────────────────
    print("  [1/4] Frame generation (Python/numpy, no encoding)...")
    frame_times = np.linspace(0, final.duration - 1/fps, n_frames)
    t0 = time.perf_counter()
    for t in frame_times:
        final.get_frame(t)
    frame_gen_time = time.perf_counter() - t0
    gen_fps = n_frames / frame_gen_time
    print(f"        {frame_gen_time:.2f}s total  ({gen_fps:.1f} frames/s Python-side)\n")

    # ── 2. Preset comparison ──────────────────────────────────────────────────
    print("  [2/4] Preset comparison (no audio, same clip)...")
    preset_results: list[tuple[str, float]] = []
    for preset in ("ultrafast", "veryfast", "fast", "medium"):
        out = f"/tmp/profile_preset_{preset}.mp4"
        t0 = time.perf_counter()
        final.write_videofile(out, fps=fps, codec="libx264", audio=False,
                              preset=preset, threads=4, logger=None)
        elapsed = time.perf_counter() - t0
        preset_results.append((preset, elapsed))
        speedup = preset_results[0][1] / elapsed if preset != "ultrafast" else 1.0
        print(f"        preset={preset:<12} {elapsed:6.2f}s", end="")
        if preset != "ultrafast":
            slower = elapsed / preset_results[0][1]
            print(f"  ({slower:.1f}× slower than ultrafast)", end="")
        print()

    # ── 3. FPS comparison ─────────────────────────────────────────────────────
    print("\n  [3/4] FPS comparison (ultrafast preset)...")
    for test_fps in (24, 30):
        out = f"/tmp/profile_fps_{test_fps}.mp4"
        t0 = time.perf_counter()
        final.write_videofile(out, fps=test_fps, codec="libx264", audio=False,
                              preset="ultrafast", threads=4, logger=None)
        elapsed = time.perf_counter() - t0
        print(f"        fps={test_fps}  {elapsed:6.2f}s")

    # ── 4. Analysis ───────────────────────────────────────────────────────────
    ultrafast_time = preset_results[0][1]
    medium_time    = preset_results[-1][1]
    # frame_gen_time is the Python bottleneck; ultrafast ~ minimum encode time
    python_pct  = frame_gen_time / medium_time * 100
    ffmpeg_pct  = (medium_time - frame_gen_time) / medium_time * 100 if medium_time > frame_gen_time else 0

    print(f"""
  ── Interpretation ────────────────────────────────────────────
  Frame generation : {frame_gen_time:6.2f}s  ({python_pct:.0f}% of medium encode time)
  │  → MoviePy calls make_frame() for every frame sequentially.
  │    If this is large, the bottleneck is Python/numpy rendering,
  │    not ffmpeg.  Fix: pre-render overlay images once (they are
  │    static), reduce composite layers, or lower fps.
  │
  ultrafast encode : {ultrafast_time:6.2f}s  (minimum possible with libx264)
  medium encode    : {medium_time:6.2f}s  (current)
  │
  Estimated breakdown of medium encode:
    Python frame gen  ≈ {frame_gen_time:.1f}s
    ffmpeg overhead   ≈ {max(0, medium_time - frame_gen_time):.1f}s
  ──────────────────────────────────────────────────────────────
  Easy wins to try:
    • preset="veryfast" saves {medium_time - preset_results[1][1]:.1f}s vs medium (minimal quality loss)
    • fps=24 instead of 30 → ~20% fewer frames
    • pre-render static overlay frames (title/review/outro) to numpy
      arrays once and use ImageClip — avoids re-drawing each frame
  ──────────────────────────────────────────────────────────────
""")


def prerender_compare(photo_paths: list[str], include_map: bool, music_path: str | None) -> None:
    """
    Compare standard MoviePy encode vs pre-render-then-encode strategy.

    Standard:  MoviePy generates each frame on-demand while piping to ffmpeg
               (Python and ffmpeg run serially, frame by frame).

    Pre-render: All frames are generated into a numpy array first, then a new
                VideoClip backed by that array is encoded.  ffmpeg can consume
                frames at full speed because Python work is already done.
    """
    from moviepy import AudioFileClip, VideoClip
    from moviepy import afx

    fps = 30
    out_standard  = "/tmp/profile_standard.mp4"
    out_prerender = "/tmp/profile_prerender.mp4"

    print("\n══ Pre-render strategy comparison ═══════════════════════════════")

    # ── Standard encode (baseline) ───────────────────────────────────────────
    print("  [1/3] Standard encode (current approach)...")
    final, _ = _build_composite(photo_paths, include_map, music_path)
    t0 = time.perf_counter()
    final.write_videofile(out_standard, fps=fps, codec="libx264",
                          audio=music_path is not None, audio_codec="aac",
                          preset="medium", threads=4, logger=None)
    standard_time = time.perf_counter() - t0
    print(f"        {standard_time:.2f}s → {out_standard}\n")

    # ── Pre-render: generate all frames first ─────────────────────────────────
    print("  [2/3] Pre-rendering all frames to RAM...")
    final2, _ = _build_composite(photo_paths, include_map, music_path)
    n_frames = int(final2.duration * fps)
    frame_times = np.linspace(0, final2.duration - 1 / fps, n_frames)

    t0 = time.perf_counter()
    frames = [final2.get_frame(t) for t in frame_times]
    prerender_time = time.perf_counter() - t0
    ram_mb = sum(f.nbytes for f in frames) / 1e6
    print(f"        {prerender_time:.2f}s  ({ram_mb:.0f} MB in RAM, "
          f"{n_frames / prerender_time:.1f} frames/s)\n")

    # ── Encode the pre-rendered clip ──────────────────────────────────────────
    print("  [3/3] Encoding pre-rendered clip...")
    prerendered = VideoClip(
        lambda t: frames[min(int(t * fps), n_frames - 1)],
        duration=final2.duration,
    )
    if music_path:
        audio = (
            AudioFileClip(music_path)
            .subclipped(0, final2.duration)
            .with_effects([afx.AudioFadeIn(0.5), afx.AudioFadeOut(0.5)])
        )
        prerendered = prerendered.with_audio(audio)

    t0 = time.perf_counter()
    prerendered.write_videofile(out_prerender, fps=fps, codec="libx264",
                                audio=music_path is not None, audio_codec="aac",
                                preset="medium", threads=4, logger=None)
    encode_only_time = time.perf_counter() - t0
    prerender_total = prerender_time + encode_only_time
    print(f"        encode: {encode_only_time:.2f}s")
    print(f"        total (pre-render + encode): {prerender_total:.2f}s → {out_prerender}\n")

    # ── Summary ───────────────────────────────────────────────────────────────
    delta = standard_time - prerender_total
    pct   = delta / standard_time * 100
    print("  ── Results ───────────────────────────────────────────────────")
    print(f"  Standard (current)          : {standard_time:.2f}s")
    print(f"  Pre-render + encode (new)   : {prerender_total:.2f}s"
          f"  ({prerender_time:.2f}s render + {encode_only_time:.2f}s encode)")
    if delta > 0:
        print(f"  Speedup                     : {delta:.2f}s faster  ({pct:.0f}% reduction)")
    else:
        print(f"  Result                      : {-delta:.2f}s slower — pre-render not beneficial here")
    print("  ──────────────────────────────────────────────────────────────\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile video generation")
    parser.add_argument(
        "--photos", nargs="+", metavar="PATH",
        help="Explicit photo paths to use instead of auto-discovery",
    )
    parser.add_argument(
        "--session-dir", metavar="PATH",
        help="Path to a specific session directory (uses its photos/ or thumbs/)",
    )
    parser.add_argument(
        "--music", metavar="PATH",
        help="Path to an MP3 file to include in encoding (adds audio encoding step)",
    )
    parser.add_argument(
        "--map", action="store_true",
        help="Enable map slide (triggers staticmap HTTP tile fetches)",
    )
    parser.add_argument(
        "--output", metavar="PATH", default="/tmp/profile_video_output.mp4",
        help="Output MP4 path (default: /tmp/profile_video_output.mp4)",
    )
    parser.add_argument(
        "--analyze", action="store_true",
        help=(
            "Deep encode analysis: measure frame generation time, compare presets "
            "(ultrafast/veryfast/fast/medium) and fps (24 vs 30)"
        ),
    )
    parser.add_argument(
        "--prerender", action="store_true",
        help=(
            "Compare standard encode vs pre-render-all-frames-then-encode strategy. "
            "Pre-rendering dumps all frames to RAM first so ffmpeg encodes at full speed."
        ),
    )
    args = parser.parse_args()

    # --- Resolve photo paths ---
    if args.photos:
        photo_paths = args.photos
    elif args.session_dir:
        session = pathlib.Path(args.session_dir)
        photos_dir = session / "photos"
        jpgs = sorted(photos_dir.glob("*.jpg")) if photos_dir.exists() else []
        if not jpgs:
            thumbs_dir = session / "thumbs"
            jpgs = sorted(thumbs_dir.glob("*.jpg")) if thumbs_dir.exists() else []
        if not jpgs:
            print(f"ERROR: no photos found in {args.session_dir}", file=sys.stderr)
            sys.exit(1)
        photo_paths = [str(p) for p in jpgs]
    else:
        workspace = ROOT / "web_workspace"
        photo_paths = _find_photos_in_sessions(workspace)

    if not photo_paths:
        print(
            "ERROR: no photos found.\n"
            "Run the web app first to create a session, or pass --photos <path>...",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"  [profile] Using {len(photo_paths)} photo(s): {photo_paths[0]} ...")

    if args.analyze:
        analyze_encode(photo_paths, args.map, args.music)
        return

    if args.prerender:
        prerender_compare(photo_paths, args.map, args.music)
        return

    print(f"  [profile] Output: {args.output}")
    if args.map:
        print(f"  [profile] Map enabled (lat={SAMPLE_LAT}, lng={SAMPLE_LNG})")
    if args.music:
        print(f"  [profile] Music: {args.music}")
    print()

    wall_start = time.perf_counter()

    build_video(
        business_name=SAMPLE_BUSINESS,
        rating=SAMPLE_RATING,
        photo_paths=photo_paths,
        reviews=SAMPLE_REVIEWS,
        output_path=args.output,
        fps=30,
        website_url="https://example.com",
        music_path=args.music,
        music_offset=0.0,
        maps_url="https://maps.google.com/?q=Le+Bacaro+Toulouse",
        city=SAMPLE_CITY,
        country=SAMPLE_COUNTRY,
        country_code=SAMPLE_COUNTRY_CODE,
        lat=SAMPLE_LAT if args.map else None,
        lng=SAMPLE_LNG if args.map else None,
    )

    wall_total = time.perf_counter() - wall_start
    print(f"  [profile] Wall clock total: {wall_total:.2f}s")


if __name__ == "__main__":
    main()
