import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_MODEL_DIR = _PROJECT_ROOT  # kokoro-tts expects model files in cwd

KOKORO_VOICE = "am_adam"


def generate_tts(text: str, output_path: str) -> str | None:
    """Generate speech for *text* using kokoro-tts and write MP3 to *output_path*.

    Returns *output_path* on success, None if kokoro-tts is unavailable.
    """
    kokoro_bin = _find_kokoro()
    if not kokoro_bin:
        logger.warning("kokoro-tts not found — skipping TTS generation")
        return None

    model_ok, missing = _check_models()
    if not model_ok:
        logger.warning("kokoro-tts model files missing (%s) — skipping TTS", missing)
        return None

    try:
        result = subprocess.run(
            [
                kokoro_bin,
                "-",  # read text from stdin
                output_path,
                "--voice", KOKORO_VOICE,
                "--format", "mp3",
                "--lang", "en-us",
            ],
            input=text.encode(),
            capture_output=True,
            cwd=str(_MODEL_DIR),
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning(
                "kokoro-tts failed (rc=%d): %s",
                result.returncode,
                result.stderr.decode(errors="replace")[:400],
            )
            return None
        logger.info("tts generated: %s (%d bytes)", output_path, Path(output_path).stat().st_size)
        return output_path
    except Exception as exc:
        logger.warning("kokoro-tts error: %s", exc)
        return None


def extract_highlight_phrases(text: str) -> list[str]:
    """Extract 1-2 short phrases from *text* to highlight in the video."""
    import re

    STRONG_WORDS = re.compile(
        r"\b(amazing|incredible|fantastic|wonderful|excellent|outstanding|"
        r"terrible|horrible|awful|worst|best|great|bad|love|hate|perfect|"
        r"beautiful|delicious|disgusting|recommend|avoid|must.visit|must.try)\b",
        re.IGNORECASE,
    )

    phrases: list[str] = []

    for m in STRONG_WORDS.finditer(text):
        start = m.start()
        # grab the 3–4 word window containing the match
        before = text[:start].split()
        after = text[start:].split()
        window = (before[-1:] if before else []) + after[:3]
        phrase = " ".join(window).strip(" .,!?;:")
        if phrase and phrase not in phrases:
            phrases.append(phrase)
        if len(phrases) >= 2:
            break

    if not phrases:
        # fallback: first 4 words of first sentence
        m2 = re.match(r"^([^.!?]+[.!?]?)", text)
        sentence = m2.group(1).strip() if m2 else text[:60]
        phrases = [" ".join(sentence.split()[:4])]

    return phrases


def get_audio_duration_seconds(path: str) -> float | None:
    """Return duration of an audio file in seconds using ffprobe."""
    import json
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            dur = stream.get("duration")
            if dur:
                return float(dur)
        return None
    except Exception as exc:
        logger.warning("ffprobe duration probe failed: %s", exc)
        return None


def _find_kokoro() -> str | None:
    import shutil
    return shutil.which("kokoro-tts")


def _check_models() -> tuple[bool, list[str]]:
    required = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]
    missing = [f for f in required if not (_MODEL_DIR / f).exists()]
    return len(missing) == 0, missing
