#!/usr/bin/env bash
# Download Kokoro TTS model files to ~/.local/share/kokoro.
# These files are required for voice-over generation.
set -euo pipefail

DEST="$HOME/.local/share/kokoro"
mkdir -p "$DEST"

RELEASE="https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0"

if [ ! -f "$DEST/kokoro-v1.0.onnx" ]; then
  echo "Downloading kokoro-v1.0.onnx (~300 MB)…"
  wget -q --show-progress "$RELEASE/kokoro-v1.0.onnx" -O "$DEST/kokoro-v1.0.onnx"
else
  echo "kokoro-v1.0.onnx already present."
fi

if [ ! -f "$DEST/voices-v1.0.bin" ]; then
  echo "Downloading voices-v1.0.bin…"
  wget -q --show-progress "$RELEASE/voices-v1.0.bin" -O "$DEST/voices-v1.0.bin"
else
  echo "voices-v1.0.bin already present."
fi

echo "Installing kokoro-tts CLI…"
uv tool install kokoro-tts

echo "Done. Run 'kokoro-tts --help-voices' to verify."
