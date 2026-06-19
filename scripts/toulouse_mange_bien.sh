#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

GEOJSON="/home/alx/code/travel-guide/static/toulouse-mange-bien/locations.geojson"

cd "$REPO"

exec uv run python -m src.geojson_to_youtube \
  "$GEOJSON" \
  --output-dir output/toulouse_mange_bien \
  --music-dir mp3/ \
  --lang fr-fr \
  --voice ff_siwis \
  --playlist-title "Toulouse Mange Bien" \
  "$@"
