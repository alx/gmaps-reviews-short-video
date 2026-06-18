"""Re-render the Gaya session with the latest sidecar/Remotion features."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

SESSION_ID = "9523889e-5c94-4d9c-b803-00a3f8ffbdd1"
PROJECT_ROOT = Path(__file__).parent.parent
SESSION_DIR = PROJECT_ROOT / "web_workspace" / "sessions" / SESSION_ID
SIDECAR_BASE = "http://127.0.0.1:3001"
SIDECAR_DIR = PROJECT_ROOT / "remotion-sidecar"

# Gaya coordinates (extracted from maps URL — not stored in session metadata)
GAYA_LAT = 9.4693212
GAYA_LNG = 100.0491771


def restart_sidecar() -> subprocess.Popen:
    """Kill any running sidecar, start a fresh one, and wait until it's ready."""
    # Kill whatever is holding port 3001 (the node server.mjs process)
    subprocess.run(["fuser", "-k", "3001/tcp"], capture_output=True)
    time.sleep(1)

    # Clear webpack filesystem cache so the fresh bundle picks up TSX changes
    import shutil
    cache_dir = SIDECAR_DIR / "node_modules" / ".cache" / "webpack"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        print("Cleared webpack cache.")
    # Also remove old /tmp bundle dirs so there's no confusion
    import glob
    for d in glob.glob("/tmp/remotion-webpack-bundle-*"):
        shutil.rmtree(d, ignore_errors=True)

    log_path = PROJECT_ROOT / "logs" / "sidecar.log"
    log_path.parent.mkdir(exist_ok=True)
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        ["npm", "start"],
        cwd=str(SIDECAR_DIR),
        stdout=log_file,
        stderr=log_file,
    )
    print(f"Sidecar restarted (PID {proc.pid}), waiting for bundle…", flush=True)

    for _ in range(60):
        try:
            r = httpx.get(f"{SIDECAR_BASE}/health", timeout=2)
            if r.status_code == 200:
                print("Sidecar ready.")
                return proc
        except Exception:
            pass
        time.sleep(2)

    print("ERROR: sidecar did not become ready in time.")
    proc.terminate()
    sys.exit(1)


def asset_url(path: str | Path) -> str:
    rel = os.path.relpath(str(path), str(PROJECT_ROOT))
    return f"{SIDECAR_BASE}/assets/{rel}"


def get_audio_duration(path: Path) -> float | None:
    try:
        from mutagen.mp3 import MP3
        return MP3(str(path)).info.length
    except Exception as e:
        print(f"  Warning: could not read TTS duration: {e}")
        return None


def main() -> None:
    restart_sidecar()

    meta = json.loads((SESSION_DIR / "metadata.json").read_text())

    photos_dir = SESSION_DIR / "photos"
    photo_paths = sorted(photos_dir.glob("photo_*.jpg"))
    if not photo_paths:
        photo_paths = sorted(photos_dir.glob("*.jpg"))
    print(f"Photos found: {len(photo_paths)}")

    map_png = SESSION_DIR / "map.png"
    map_image_url = asset_url(map_png) if map_png.exists() else ""

    mini_map_png = SESSION_DIR / "mini_map.png"
    if not mini_map_png.exists():
        sys.path.insert(0, str(PROJECT_ROOT))
        from src import video as video_mod
        print("Generating mini-map (OSM, zoom 16)…")
        video_mod.render_mini_map(GAYA_LAT, GAYA_LNG, str(mini_map_png))
    mini_map_url = asset_url(mini_map_png) if mini_map_png.exists() else ""
    print(f"Mini-map: {'OK' if mini_map_url else 'MISSING'}")

    tts_mp3 = SESSION_DIR / "tts.mp3"
    tts_url = asset_url(tts_mp3) if tts_mp3.exists() else ""
    tts_duration = get_audio_duration(tts_mp3) if tts_mp3.exists() else None
    if tts_duration:
        print(f"TTS duration: {tts_duration:.2f}s")

    music_path = meta.get("music", "")
    review = meta["review"]

    input_props = {
        "businessName": meta["business_name"],
        "rating": float(meta["rating"]),
        "city": "",
        "country": "",
        "countryCode": "",
        "websiteUrl": meta.get("website_url", ""),
        "mapsUrl": meta["maps_url"],
        "review": review,
        "photoUrls": [asset_url(p) for p in photo_paths],
        "mapImageUrl": map_image_url,
        "miniMapUrl": mini_map_url,
        "musicUrl": asset_url(music_path) if music_path else "",
        "musicOffset": 0.0,
        "industryVibe": meta.get("industry_vibe", "other"),
        "reviewStyle": "highlight",
        "highlightPhrases": [],
        "ttsUrl": tts_url,
        "ttsDurationSeconds": tts_duration,
        "structure": "default",
        "reviews": [review],
        "tagline": "",
        "titleFont": "PlayfairDisplay",
        "sunBleach": False,
        "cards": {
            "intro":  {"enabled": True},
            "review": {"enabled": True},
            "map":    {"enabled": bool(map_image_url)},
            "outro":  {"enabled": True, "showQr": True, "showWebsite": True},
        },
    }

    output_path = str(SESSION_DIR / "video_latest.mp4")
    print(f"Posting render job → {output_path}")

    resp = httpx.post(
        f"{SIDECAR_BASE}/render",
        json={"outputPath": output_path, "inputProps": input_props},
        timeout=15,
    )
    resp.raise_for_status()
    job_id = resp.json()["jobId"]
    print(f"Job ID: {job_id}")

    while True:
        prog = httpx.get(f"{SIDECAR_BASE}/jobs/{job_id}", timeout=10).json()
        pct = int(prog["progress"] * 100)
        print(f"\r  Progress: {pct}%  ", end="", flush=True)
        if prog["done"]:
            print()
            if prog["error"]:
                print(f"ERROR: {prog['error']}")
                sys.exit(1)
            break
        time.sleep(1)

    print(f"Done! Output: {output_path}")


if __name__ == "__main__":
    main()
