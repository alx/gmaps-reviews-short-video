#!/usr/bin/env bash
# Download Kokoro TTS model files to the project root.
# These files are required for voice-over generation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."

cd "$ROOT"

RELEASE="https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0"

if [ ! -f "kokoro-v1.0.onnx" ]; then
  echo "Downloading kokoro-v1.0.onnx (~300 MB)…"
  wget -q --show-progress "$RELEASE/kokoro-v1.0.onnx"
else
  echo "kokoro-v1.0.onnx already present."
fi

if [ ! -f "voices-v1.0.bin" ]; then
  echo "Downloading voices-v1.0.bin…"
  wget -q --show-progress "$RELEASE/voices-v1.0.bin"
else
  echo "voices-v1.0.bin already present."
fi

echo "Installing kokoro-tts CLI…"
uv tool install kokoro-tts

echo "Done. Run 'kokoro-tts --help-voices' to verify."
