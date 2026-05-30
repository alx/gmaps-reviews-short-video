# gmaps-reviews-short-video

Generate a 7-second short-form video from a Google Maps business URL. Combines a Ken Burns photo slideshow, star-rating overlay, top customer reviews, and optional background music — ready to post on Instagram Reels, TikTok, or YouTube Shorts.

## Features

- Fetches business name, rating, photos, and reviews via the **Google Maps Places API (New)**
- Ken Burns zoom effect across up to 5 business photos with crossfades
- Semi-transparent review cards with author name, stars, and review text
- Outro card with business name and website URL
- Optional background music with fade in/out
- Outputs a 1080×1920 MP4 (portrait / 9:16)

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- A Google Maps Platform API key with the **Places API (New)** enabled
- `ffmpeg` installed and available on your `PATH`

## Setup

```bash
git clone https://github.com/alx/gmaps-reviews-short-video.git
cd gmaps-reviews-short-video
cp .env.example .env
# Edit .env and set your GOOGLE_MAPS_API_KEY
uv sync
```

## Usage

```bash
uv run gmaps-reviews-short-video "https://www.google.com/maps/place/..."
```

With options:

```bash
uv run gmaps-reviews-short-video \
  "https://www.google.com/maps/place/..." \
  --output output/my_video.mp4 \
  --music mp3/alec_koff-carnaval-484622.mp3
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--output FILE` | `output/output.mp4` | Output video file path |
| `--music FILE` | _(none)_ | Path to an MP3/WAV for background music |

## Development

```bash
uv sync --group dev
uv run pytest
```

## Sample Music

`mp3/alec_koff-carnaval-484622.mp3` — "Carnaval" by Alec Koff, licensed from
[Pixabay](https://pixabay.com/music/samba-latin-carnaval-484622/) under the
[Pixabay Content License](mp3/samba-latin-carnaval-484622-license.txt).

## License

[MIT](LICENSE)
