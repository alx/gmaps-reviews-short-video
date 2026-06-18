import contextlib as _contextlib
import datetime
import logging
import os
import random
import subprocess
import textwrap
import time as _time

logger = logging.getLogger(__name__)

_timings: list[tuple[str, float]] = []

@_contextlib.contextmanager
def _timer(label: str):
    t0 = _time.perf_counter()
    yield
    _timings.append((label, _time.perf_counter() - t0))

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoClip,
)
from moviepy import afx, vfx

W, H = 1080, 1920
TOTAL = 12.0
MAP_DUR = 3.0    # map slide between review and outro
CROSSFADE = 0.5
FADE = 0.5       # global fade-in from black / fade-to-black duration
OUTRO_DUR = 5.0  # seconds the outro card is visible before the video ends
TITLE_DUR = 2.0  # seconds the title card is visible at the start

_OSM_CARTO = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
# Safe zone on the right (UI chrome)
SAFE_RIGHT  = 160
# Review card — large, spans most of the visible frame
CARD_Y_TOP  = 120
CARD_Y_BOT  = 1560
CARD_H      = CARD_Y_BOT - CARD_Y_TOP   # 1440
CARD_W      = W - SAFE_RIGHT             # 920
CARD_X      = (W - CARD_W) // 2         # 80

# 15s Scénographie structure — cross-platform safe zones (TikTok + Reels)
_S15_SAFE_TOP  = 250
_S15_SAFE_BOT  = 420
_S15_CARD_Y_TOP = _S15_SAFE_TOP           # 250
_S15_CARD_Y_BOT = H - _S15_SAFE_BOT       # 1500
_S15_CARD_W    = W - 80                    # 1000 (40 px each side)
_S15_CARD_X    = (W - _S15_CARD_W) // 2   # 40


def find_font() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for f in candidates:
        if os.path.exists(f):
            return f
    raise RuntimeError("No bold font found. Install dejavu-fonts-ttf.")


def find_font_regular() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for f in candidates:
        if os.path.exists(f):
            return f
    return find_font()


def find_emoji_font() -> str | None:
    path = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
    return path if os.path.exists(path) else None


_EMOJI_FONT_SIZE = 109  # NotoColorEmoji only has bitmap strikes at this size


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return cp > 0x2600 and cp not in (0xFE0F, 0x200D)


def _draw_mixed_text(
    frame: Image.Image,
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    text_font,
    emoji_font_path: str | None,
    fill: tuple,
    line_h: int,
    canvas_w: int,
) -> None:
    """Render text with inline color emoji, centered horizontally on canvas_w."""
    # Split into (is_emoji, segment) runs
    runs: list[tuple[bool, str]] = []
    for ch in text:
        if ch in ("️", "‍"):
            continue
        is_e = _is_emoji(ch)
        if runs and runs[-1][0] == is_e:
            runs[-1] = (is_e, runs[-1][1] + ch)
        else:
            runs.append((is_e, ch))

    emoji_font = None
    if emoji_font_path:
        try:
            emoji_font = ImageFont.truetype(emoji_font_path, _EMOJI_FONT_SIZE)
        except Exception:
            pass

    # Measure total width to center
    total_w = 0
    for is_e, seg in runs:
        if is_e and emoji_font:
            tmp = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
            td = ImageDraw.Draw(tmp)
            bb = td.textbbox((0, 0), seg, font=emoji_font, embedded_color=True)
            raw_w, raw_h = bb[2] - bb[0], bb[3] - bb[1]
            scale = line_h / raw_h if raw_h else 1.0
            total_w += int(raw_w * scale)
        else:
            bb = draw.textbbox((0, 0), seg, font=text_font)
            total_w += bb[2] - bb[0]

    x = (canvas_w - total_w) // 2

    for is_e, seg in runs:
        if is_e and emoji_font:
            tmp = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
            td = ImageDraw.Draw(tmp)
            td.text((0, 0), seg, font=emoji_font, embedded_color=True)
            bb = td.textbbox((0, 0), seg, font=emoji_font, embedded_color=True)
            raw_w = bb[2] - bb[0]
            raw_h = bb[3] - bb[1]
            if raw_h == 0:
                continue
            scale = line_h / raw_h
            scaled_w = max(1, int(raw_w * scale))
            scaled_h = max(1, line_h)
            glyph = tmp.crop((bb[0], bb[1], bb[2], bb[3]))
            glyph = glyph.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
            paste_y = y + (line_h - scaled_h) // 2
            frame.paste(glyph, (x, paste_y), glyph)
            x += scaled_w
        else:
            bb = draw.textbbox((0, 0), seg, font=text_font)
            seg_h = bb[3] - bb[1]
            seg_y = y + (line_h - seg_h) // 2
            draw.text((x, seg_y), seg, font=text_font, fill=fill)
            x += bb[2] - bb[0]


def load_and_fit_image(path: str, target_w: int = W, target_h: int = H) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    scale = max(target_w / img.width, target_h / img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))
    return np.array(img)


def make_ken_burns_clip(path: str, duration: float, zoom: float = 1.08) -> VideoClip:
    oversized_w = int(W * zoom)
    oversized_h = int(H * zoom)
    arr = load_and_fit_image(path, oversized_w, oversized_h)

    def make_frame(t: float) -> np.ndarray:
        # Zoom from 1.0 to zoom over the duration, then crop center to W×H
        progress = t / duration
        current_zoom = 1.0 + (zoom - 1.0) * progress
        # How much of the oversized image to show
        crop_w = int(W / current_zoom * zoom)
        crop_h = int(H / current_zoom * zoom)
        # Clamp to actual array size
        crop_w = min(crop_w, oversized_w)
        crop_h = min(crop_h, oversized_h)
        left = (oversized_w - crop_w) // 2
        top = (oversized_h - crop_h) // 2
        cropped = arr[top : top + crop_h, left : left + crop_w]
        frame = np.array(
            Image.fromarray(cropped).resize((W, H), Image.Resampling.BILINEAR)
        )
        return frame

    return VideoClip(make_frame, duration=duration)


def truncate_review(text: str, limit: int = 100) -> str:
    if len(text) <= limit:
        return text
    truncated = text[:limit].rsplit(' ', 1)[0]
    return truncated.rstrip('.,;') + '…'


def _country_flag(code: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper() if c.isalpha())


def make_review_card(review: dict, font_path: str, font_bold_path: str) -> tuple[np.ndarray, np.ndarray, int]:
    pad = 48
    y_start = 32
    line_h = 60

    text = truncate_review(review["text"])
    lines = textwrap.wrap(text, width=34)

    # Size the card to exactly fit the content
    actual_h = y_start + 66 + 24 + len(lines) * line_h + pad
    actual_h = min(actual_h, CARD_H)

    card = Image.new("RGBA", (CARD_W, actual_h), (0, 0, 0, 0))
    bg = Image.new("RGBA", (CARD_W, actual_h), (15, 15, 15, 210))
    card.paste(bg, (0, 0))
    draw = ImageDraw.Draw(card)

    y = y_start

    # Star rating + author line
    stars = "★" * int(review["rating"]) + "☆" * (5 - int(review["rating"]))
    author = review["author"] or "Customer"
    header_text = f"{stars}  {author}"
    try:
        hfont = ImageFont.truetype(font_bold_path, 44)
    except Exception:
        hfont = ImageFont.load_default()
    draw.text((pad, y), header_text, font=hfont, fill=(255, 210, 50, 255),
              stroke_width=2, stroke_fill=(0, 0, 0, 255))
    y += 66

    # Divider
    draw.line([(pad, y), (CARD_W - pad, y)], fill=(255, 255, 255, 60), width=1)
    y += 24

    try:
        rfont = ImageFont.truetype(font_path, 42)
    except Exception:
        rfont = ImageFont.load_default()

    for line in lines:
        draw.text((pad, y), line, font=rfont, fill=(240, 240, 240, 255),
                  stroke_width=3, stroke_fill=(0, 0, 0, 255))
        y += line_h

    alpha = np.array(card.split()[3]).astype(float) / 255.0
    return np.array(card.convert("RGB")), alpha, actual_h


def _render_qr(url: str, size: int) -> Image.Image:
    return qrcode.make(url).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def make_outro_card(
    business_name: str, website_url: str, font_bold: str, font_reg: str,
    maps_url: str = "",
    city: str = "", country: str = "", country_code: str = "",
) -> ImageClip:
    QR_SIZE = 600
    QR_PAD = 40  # space between text block and QR code

    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bg = Image.new("RGBA", (W, H), (10, 10, 15, 210))
    frame.paste(bg)
    draw = ImageDraw.Draw(frame)

    try:
        name_font = ImageFont.truetype(font_bold, 64)
    except Exception:
        name_font = ImageFont.load_default()
    try:
        url_font = ImageFont.truetype(font_reg, 32)
    except Exception:
        url_font = ImageFont.load_default()
    try:
        loc_font = ImageFont.truetype(font_reg, 40)
    except Exception:
        loc_font = ImageFont.load_default()

    name_lines = textwrap.wrap(business_name, width=20) or [business_name]
    line_h = 80
    has_url = bool(website_url)
    has_loc = bool(city or country)
    LOC_LINE_H = 56
    LOC_GAP = 16
    LOC_TOP_PAD = 24
    loc_h = (LOC_TOP_PAD + LOC_LINE_H + LOC_GAP + LOC_LINE_H) if has_loc else 0
    text_h = len(name_lines) * line_h + (60 if has_url else 0) + loc_h
    POST_QR_PAD  = 24
    LABEL_LINE_H = 104
    CTA_LINE_H   = 88
    LINE_GAP     = 10
    has_qr = bool(maps_url)
    post_qr_h = (POST_QR_PAD + LABEL_LINE_H + LINE_GAP + CTA_LINE_H) if has_qr else 0
    total_block_h = text_h + (QR_PAD + QR_SIZE if has_qr else 0) + post_qr_h
    text_top = (H - total_block_h) // 2

    for i, line in enumerate(name_lines):
        bbox = draw.textbbox((0, 0), line, font=name_font)
        x = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x, text_top + i * line_h), line, font=name_font, fill=(255, 255, 255, 255))

    if has_url:
        short_url = website_url if len(website_url) <= 42 else website_url[:39] + "…"
        url_y = text_top + len(name_lines) * line_h + 20
        url_bbox = draw.textbbox((0, 0), short_url, font=url_font)
        url_x = (W - (url_bbox[2] - url_bbox[0])) // 2
        draw.text((url_x, url_y), short_url, font=url_font, fill=(170, 170, 170, 255))

    if has_loc:
        emoji_fp = find_emoji_font()
        name_block_bottom = text_top + len(name_lines) * line_h + (60 if has_url else 0)
        loc_y = name_block_bottom + LOC_TOP_PAD
        if city:
            city_bbox = draw.textbbox((0, 0), city, font=loc_font)
            city_x = (W - (city_bbox[2] - city_bbox[0])) // 2
            draw.text((city_x, loc_y), city, font=loc_font, fill=(200, 200, 200, 255))
        loc_y += LOC_LINE_H + LOC_GAP
        if country:
            flag = _country_flag(country_code) + " " if country_code else ""
            _draw_mixed_text(frame, draw, loc_y, f"{flag}{country}",
                             loc_font, emoji_fp, (200, 200, 200, 255), LOC_LINE_H, W)

    if has_qr:
        qr_img = _render_qr(maps_url, QR_SIZE)
        qr_x = (W - QR_SIZE) // 2
        qr_y = text_top + text_h + QR_PAD
        frame.paste(qr_img, (qr_x, qr_y), qr_img)

        try:
            label_font = ImageFont.truetype(font_reg, 72)
            cta_font   = ImageFont.truetype(font_reg, 60)
        except Exception:
            label_font = cta_font = ImageFont.load_default()

        label_y = qr_y + QR_SIZE + POST_QR_PAD
        cta_y   = label_y + LABEL_LINE_H + LINE_GAP
        emoji_fp = find_emoji_font()

        _draw_mixed_text(frame, draw, label_y, "📍 Google Maps ⬆",
                         label_font, emoji_fp, (200, 200, 200, 255), LABEL_LINE_H, W)
        # _draw_mixed_text(frame, draw, cta_y, "📤 Share this QR Code",
        #                  cta_font, emoji_fp, (150, 150, 150, 255), CTA_LINE_H, W)

    alpha = np.array(frame.split()[3]).astype(float) / 255.0
    rgb = np.array(frame.convert("RGB"))
    clip = ImageClip(rgb)
    mask = ImageClip(alpha, is_mask=True)
    return clip.with_mask(mask)


def make_title_card(
    business_name: str, rating: float, font_bold: str, font_reg: str,
    photo_path: str | None = None,
    city: str = "", country: str = "", country_code: str = "",
) -> ImageClip:
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    if photo_path:
        photo = Image.fromarray(load_and_fit_image(photo_path)).convert("RGBA")
        photo.putalpha(77)  # ~30% opacity
        frame = Image.alpha_composite(frame, photo)
    dark_overlay = Image.new("RGBA", (W, H), (10, 10, 15, 170))
    frame = Image.alpha_composite(frame, dark_overlay)
    draw = ImageDraw.Draw(frame)

    try:
        name_font = ImageFont.truetype(font_bold, 80)
    except Exception:
        name_font = ImageFont.load_default()
    try:
        star_font = ImageFont.truetype(font_reg, 52)
    except Exception:
        star_font = ImageFont.load_default()
    try:
        loc_font = ImageFont.truetype(font_reg, 44)
    except Exception:
        loc_font = ImageFont.load_default()

    name_lines = textwrap.wrap(business_name, width=16) or [business_name]
    line_h = 100
    stars_text = "★" * round(rating) + "☆" * (5 - round(rating)) + f"  {rating:.1f}"
    has_loc = bool(city or country)
    LOC_LINE_H = 60
    LOC_GAP = 12
    LOC_TOP_PAD = 20
    loc_h = (LOC_TOP_PAD + LOC_LINE_H + LOC_GAP + LOC_LINE_H) if has_loc else 0
    total_text_h = len(name_lines) * line_h + 80 + loc_h
    text_top = (H - total_text_h) // 2

    for i, line in enumerate(name_lines):
        bbox = draw.textbbox((0, 0), line, font=name_font)
        x = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x, text_top + i * line_h), line, font=name_font,
                  fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))

    stars_y = text_top + len(name_lines) * line_h + 24
    stars_bbox = draw.textbbox((0, 0), stars_text, font=star_font)
    stars_x = (W - (stars_bbox[2] - stars_bbox[0])) // 2
    draw.text((stars_x, stars_y), stars_text, font=star_font, fill=(255, 210, 50, 255))

    if has_loc:
        emoji_fp = find_emoji_font()
        loc_y = stars_y + 56 + LOC_TOP_PAD  # below stars line
        if city:
            city_bbox = draw.textbbox((0, 0), city, font=loc_font)
            city_x = (W - (city_bbox[2] - city_bbox[0])) // 2
            draw.text((city_x, loc_y), city, font=loc_font, fill=(255, 255, 255, 255))
        loc_y += LOC_LINE_H + LOC_GAP
        if country:
            flag = _country_flag(country_code) + " " if country_code else ""
            _draw_mixed_text(frame, draw, loc_y, f"{flag}{country}",
                             loc_font, emoji_fp, (255, 255, 255, 255), LOC_LINE_H, W)

    alpha = np.array(frame.split()[3]).astype(float) / 255.0
    rgb = np.array(frame.convert("RGB"))
    clip = ImageClip(rgb)
    mask = ImageClip(alpha, is_mask=True)
    return clip.with_mask(mask)


_CARTO_DARK = "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png"

MINI_MAP_SIZE = 608  # rendered at 2× (304 CSS px) for sharp display


def render_mini_map(
    lat: float,
    lng: float,
    output_path: str,
    zoom: int = 16,
) -> str | None:
    """Render an OSM neighbourhood map at walkable scale. Returns path or None."""
    try:
        from staticmap import StaticMap, CircleMarker
    except ImportError:
        return None
    try:
        m = StaticMap(MINI_MAP_SIZE, MINI_MAP_SIZE, url_template=_OSM_CARTO)
        m.add_marker(CircleMarker((lng, lat), "white", 22))
        m.add_marker(CircleMarker((lng, lat), "#E63939", 14))
        img = m.render(zoom=zoom, center=[lng, lat])
        img.convert("RGB").save(output_path, "PNG")
        return output_path
    except Exception as exc:
        logger.warning("render_mini_map failed: %s", exc)
        return None


def render_map_image(
    lat: float,
    lng: float,
    output_path: str,
    zoom: int = 15,
) -> str | None:
    """Render an OpenStreetMap PNG to disk (no text overlay). Returns path or None."""
    try:
        from staticmap import StaticMap, CircleMarker
    except ImportError:
        return None
    try:
        m = StaticMap(W, H, url_template=_OSM_CARTO)
        m.add_marker(CircleMarker((lng, lat), "white", 28))
        m.add_marker(CircleMarker((lng, lat), "#FF3333", 18))
        img = m.render(zoom=zoom, center=[lng, lat])
        img.convert("RGB").save(output_path, "PNG")
        return output_path
    except Exception as exc:
        logger.warning("render_map_image failed: %s", exc)
        return None


def make_map_slide(
    lat: float,
    lng: float,
    business_name: str,
    city: str = "",
    zoom: int = 15,
) -> ImageClip | None:
    try:
        from staticmap import StaticMap, CircleMarker
    except ImportError:
        return None

    try:
        m = StaticMap(W, H, url_template=_OSM_CARTO)
        m.add_marker(CircleMarker((lng, lat), "white", 28))
        m.add_marker(CircleMarker((lng, lat), "#FF3333", 18))
        img = m.render(zoom=zoom, center=[lng, lat])
    except Exception as exc:
        logger.warning("map slide skipped: %s", exc)
        return None

    img = img.convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    BAR_H = 220
    bar = Image.new("RGBA", (W, BAR_H), (0, 0, 0, 185))
    overlay.paste(bar, (0, H - BAR_H))

    draw = ImageDraw.Draw(overlay)
    font_bold = find_font()
    font_reg = find_font_regular()
    try:
        city_font = ImageFont.truetype(font_bold, 56)
    except Exception:
        city_font = ImageFont.load_default()
    try:
        name_font = ImageFont.truetype(font_reg, 38)
    except Exception:
        name_font = ImageFont.load_default()

    y = H - BAR_H + 28
    if city:
        bbox = draw.textbbox((0, 0), city, font=city_font)
        draw.text(((W - (bbox[2] - bbox[0])) // 2, y), city, font=city_font,
                  fill=(255, 255, 255, 255))
        y += 72
    short_name = business_name if len(business_name) <= 30 else business_name[:29] + "…"
    bbox = draw.textbbox((0, 0), short_name, font=name_font)
    draw.text(((W - (bbox[2] - bbox[0])) // 2, y), short_name, font=name_font,
              fill=(200, 200, 200, 255))

    img = Image.alpha_composite(img, overlay)
    rgb = np.array(img.convert("RGB"))
    return ImageClip(rgb)


def make_header(business_name: str, rating: float, font_bold: str) -> list:
    # Semi-transparent dark header background
    bg_arr = np.zeros((HEADER_H, W, 3), dtype=np.uint8)
    bg_clip = (
        ImageClip(bg_arr)
        .with_duration(TOTAL)
        .with_opacity(0.72)
        .with_position((0, 0))
    )

    # Stars + rating
    stars = "★" * round(rating) + f"  {rating:.1f}"
    star_clip = (
        TextClip(
            font=font_bold,
            text=stars,
            font_size=38,
            color="#FFD700",
            method="label",
        )
        .with_duration(TOTAL)
        .with_position((48, 14))
    )

    # Business name — truncate if too long
    name = business_name if len(business_name) <= 32 else business_name[:31] + "…"
    name_clip = (
        TextClip(
            font=font_bold,
            text=name,
            font_size=50,
            color="white",
            method="label",
        )
        .with_duration(TOTAL)
        .with_position((48, 66))
    )

    return [bg_clip, star_clip, name_clip]


def _embed_cover_image(output_path: str, cover_frame) -> None:
    """Mux a cover/thumbnail image into the MP4 so platforms show a non-black preview."""
    if cover_frame is None:
        return
    tmp_jpg = output_path + ".cover.jpg"
    tmp_mp4 = output_path + ".tmp.mp4"
    try:
        img = Image.fromarray(cover_frame)
        img.save(tmp_jpg, "JPEG", quality=85)
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", output_path,
                "-i", tmp_jpg,
                "-map", "0",
                "-map", "1",
                "-c", "copy",
                "-c:v:1", "mjpeg",
                "-disposition:v:1", "attached_pic",
                tmp_mp4,
            ],
            capture_output=True,
        )
        if result.returncode == 0:
            os.replace(tmp_mp4, output_path)
        else:
            logger.warning("cover image embed failed: %s", result.stderr.decode(errors="replace"))
    except Exception as exc:
        logger.warning("cover image embed skipped: %s", exc)
    finally:
        for p in (tmp_jpg, tmp_mp4):
            with _contextlib.suppress(FileNotFoundError):
                os.remove(p)


def make_hook_card(
    review: dict,
    rating: float,
    font_bold: str,
    font_reg: str,
    variant: str = "stars",
) -> ImageClip:
    """Hook segment (0–2s): large star rating OR impactful quote from the review."""
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bg = Image.new("RGBA", (W, H), (15, 15, 15, 220))
    frame.paste(bg)
    draw = ImageDraw.Draw(frame)

    safe_h = _S15_CARD_Y_BOT - _S15_CARD_Y_TOP  # 1250

    if variant == "stars":
        try:
            star_font = ImageFont.truetype(font_bold, 110)
        except Exception:
            star_font = ImageFont.load_default()
        try:
            text_font = ImageFont.truetype(font_reg, 72)
        except Exception:
            text_font = ImageFont.load_default()

        stars = "★" * int(rating) + "☆" * (5 - int(rating))
        words = review.get("text", "").split()
        quote = " ".join(words[:12]) + ("…" if len(words) > 12 else "")
        quote_lines = textwrap.wrap(quote, width=24)

        star_h = 130
        text_line_h = 90
        total_content_h = star_h + 24 + len(quote_lines) * text_line_h
        y = _S15_CARD_Y_TOP + (safe_h - total_content_h) // 2

        star_bbox = draw.textbbox((0, 0), stars, font=star_font)
        draw.text(((W - (star_bbox[2] - star_bbox[0])) // 2, y), stars,
                  font=star_font, fill=(255, 210, 50, 255))
        y += star_h + 24

        for line in quote_lines:
            lb = draw.textbbox((0, 0), line, font=text_font)
            draw.text(((W - (lb[2] - lb[0])) // 2, y), line, font=text_font,
                      fill=(240, 240, 240, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
            y += text_line_h

    else:  # variant == "quote"
        try:
            quote_font = ImageFont.truetype(font_bold, 80)
        except Exception:
            quote_font = ImageFont.load_default()
        try:
            author_font = ImageFont.truetype(font_reg, 52)
        except Exception:
            author_font = ImageFont.load_default()

        words = review.get("text", "").split()
        body = " ".join(words[:12]) + ("…" if len(words) > 12 else "")
        quote_lines = textwrap.wrap(f"\"{body}\"", width=22)
        author = review.get("author", "Customer")

        text_line_h = 100
        author_h = 70
        total_content_h = len(quote_lines) * text_line_h + 24 + author_h
        y = _S15_CARD_Y_TOP + (safe_h - total_content_h) // 2

        for line in quote_lines:
            lb = draw.textbbox((0, 0), line, font=quote_font)
            draw.text(((W - (lb[2] - lb[0])) // 2, y), line, font=quote_font,
                      fill=(240, 240, 240, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
            y += text_line_h

        y += 24
        author_text = f"— {author}"
        ab = draw.textbbox((0, 0), author_text, font=author_font)
        draw.text(((W - (ab[2] - ab[0])) // 2, y), author_text,
                  font=author_font, fill=(200, 200, 200, 255))

    alpha = np.array(frame.split()[3]).astype(float) / 255.0
    rgb = np.array(frame.convert("RGB"))
    return ImageClip(rgb).with_mask(ImageClip(alpha, is_mask=True))


def make_body_card(
    reviews: list[dict],
    font_bold: str,
    font_reg: str,
    n_reviews: int = 1,
) -> ImageClip:
    """Body segment (2–10s): 1–2 reviews in large readable text on a dark scrim."""
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bg = Image.new("RGBA", (W, H), (15, 15, 15, 220))
    frame.paste(bg)
    draw = ImageDraw.Draw(frame)

    pad = 40
    header_size = 52
    text_size = 68
    header_line_h = 66
    text_line_h = 84
    divider_gap = 20

    try:
        hfont = ImageFont.truetype(font_bold, header_size)
    except Exception:
        hfont = ImageFont.load_default()
    try:
        rfont = ImageFont.truetype(font_reg, text_size)
    except Exception:
        rfont = ImageFont.load_default()

    safe_h = _S15_CARD_Y_BOT - _S15_CARD_Y_TOP

    def render_block(review: dict, y_start: int, max_h: int) -> None:
        y = y_start
        text = truncate_review(review["text"], limit=90)
        lines = textwrap.wrap(text, width=28)
        stars = "★" * int(review["rating"]) + "☆" * (5 - int(review["rating"]))
        author = review.get("author", "Customer")
        header = f"{stars}  {author}"
        draw.text((pad, y), header, font=hfont, fill=(255, 210, 50, 255),
                  stroke_width=2, stroke_fill=(0, 0, 0, 255))
        y += header_line_h + divider_gap
        draw.line([(pad, y), (W - pad, y)], fill=(255, 255, 255, 60), width=1)
        y += divider_gap
        for line in lines:
            if y + text_line_h > y_start + max_h:
                break
            draw.text((pad, y), line, font=rfont, fill=(240, 240, 240, 255),
                      stroke_width=2, stroke_fill=(0, 0, 0, 255))
            y += text_line_h

    count = min(max(n_reviews, 1), len(reviews)) if reviews else 1

    if count == 1:
        review = reviews[0] if reviews else {"text": "", "rating": 5, "author": "Customer"}
        text = truncate_review(review["text"], limit=90)
        lines = textwrap.wrap(text, width=28)
        content_h = header_line_h + divider_gap * 2 + len(lines) * text_line_h
        y_start = _S15_CARD_Y_TOP + max((safe_h - content_h) // 2, 20)
        render_block(review, y_start, safe_h)
    else:
        half_h = safe_h // 2 - 40
        render_block(reviews[0], _S15_CARD_Y_TOP + 20, half_h)
        mid_y = _S15_CARD_Y_TOP + safe_h // 2
        draw.line([(40, mid_y), (W - 40, mid_y)], fill=(255, 255, 255, 100), width=2)
        render_block(reviews[1], mid_y + 20, half_h)

    alpha = np.array(frame.split()[3]).astype(float) / 255.0
    rgb = np.array(frame.convert("RGB"))
    return ImageClip(rgb).with_mask(ImageClip(alpha, is_mask=True))


def make_proof_card(
    business_name: str,
    rating: float,
    review_count: int,
    font_bold: str,
    font_reg: str,
) -> ImageClip:
    """Proof segment (10–13s): business name + aggregate rating + review count."""
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bg = Image.new("RGBA", (W, H), (10, 10, 15, 220))
    frame.paste(bg)
    draw = ImageDraw.Draw(frame)

    try:
        name_font = ImageFont.truetype(font_bold, 72)
    except Exception:
        name_font = ImageFont.load_default()
    try:
        stats_font = ImageFont.truetype(font_bold, 64)
    except Exception:
        stats_font = ImageFont.load_default()
    try:
        tag_font = ImageFont.truetype(font_reg, 44)
    except Exception:
        tag_font = ImageFont.load_default()

    name_lines = textwrap.wrap(business_name, width=22) or [business_name]
    name_line_h = 88
    stats_text = f"★ {rating:.1f}  ·  {review_count} avis"
    tagline = "Vos clients parlent pour vous"

    total_h = len(name_lines) * name_line_h + 24 + 80 + 24 + 60
    y = (H - total_h) // 2

    for line in name_lines:
        bbox = draw.textbbox((0, 0), line, font=name_font)
        x = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=name_font, fill=(255, 255, 255, 255))
        y += name_line_h

    y += 24
    stats_bbox = draw.textbbox((0, 0), stats_text, font=stats_font)
    x = (W - (stats_bbox[2] - stats_bbox[0])) // 2
    draw.text((x, y), stats_text, font=stats_font, fill=(255, 210, 50, 255))
    y += 80 + 24

    tag_bbox = draw.textbbox((0, 0), tagline, font=tag_font)
    x = (W - (tag_bbox[2] - tag_bbox[0])) // 2
    draw.text((x, y), tagline, font=tag_font, fill=(170, 170, 170, 255))

    alpha = np.array(frame.split()[3]).astype(float) / 255.0
    rgb = np.array(frame.convert("RGB"))
    return ImageClip(rgb).with_mask(ImageClip(alpha, is_mask=True))


def make_cta_card(
    cta_text: str,
    maps_url: str,
    font_bold: str,
    font_reg: str,
    social_handle: str = "",
) -> ImageClip:
    """CTA segment (13–15s): action text + QR code + optional social handle."""
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bg = Image.new("RGBA", (W, H), (10, 10, 15, 220))
    frame.paste(bg)
    draw = ImageDraw.Draw(frame)

    try:
        cta_font = ImageFont.truetype(font_bold, 80)
    except Exception:
        cta_font = ImageFont.load_default()
    try:
        sub_font = ImageFont.truetype(font_reg, 48)
    except Exception:
        sub_font = ImageFont.load_default()
    try:
        handle_font = ImageFont.truetype(font_reg, 44)
    except Exception:
        handle_font = ImageFont.load_default()

    QR_SIZE = 480
    has_qr = bool(maps_url)
    safe_h = _S15_CARD_Y_BOT - _S15_CARD_Y_TOP

    cta_line_h = 96
    sub_line_h = 60
    qr_gap = 32
    handle_h = 56 if social_handle else 0
    content_h = (
        cta_line_h + 16 + sub_line_h
        + (qr_gap + QR_SIZE + (16 + handle_h if social_handle else 0) if has_qr else 0)
    )
    y = _S15_CARD_Y_TOP + (safe_h - content_h) // 2

    cta_bbox = draw.textbbox((0, 0), cta_text, font=cta_font)
    x = (W - (cta_bbox[2] - cta_bbox[0])) // 2
    draw.text((x, y), cta_text, font=cta_font, fill=(255, 255, 255, 255))
    y += cta_line_h + 16

    sub_text = "Scannez pour réserver" if has_qr else "Découvrez-nous"
    sub_bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
    x = (W - (sub_bbox[2] - sub_bbox[0])) // 2
    draw.text((x, y), sub_text, font=sub_font, fill=(170, 170, 170, 255))
    y += sub_line_h

    if has_qr:
        y += qr_gap
        qr_img = _render_qr(maps_url, QR_SIZE)
        frame.paste(qr_img, ((W - QR_SIZE) // 2, y), qr_img)
        y += QR_SIZE
        if social_handle:
            y += 16
            hb = draw.textbbox((0, 0), social_handle, font=handle_font)
            x = (W - (hb[2] - hb[0])) // 2
            draw.text((x, y), social_handle, font=handle_font, fill=(170, 170, 170, 255))

    alpha = np.array(frame.split()[3]).astype(float) / 255.0
    rgb = np.array(frame.convert("RGB"))
    return ImageClip(rgb).with_mask(ImageClip(alpha, is_mask=True))


def _make_body_segment(
    reviews: list[dict],
    font_bold: str,
    font_reg: str,
    start: float,
    total_dur: float,
    n_reviews: int,
) -> list:
    """Build the body overlay clips: 1 card or a carousel of n_reviews cards."""
    count = min(max(n_reviews, 1), max(len(reviews), 1))
    if count <= 1 or len(reviews) < 2:
        clip = (
            make_body_card(reviews[:1] if reviews else [], font_bold, font_reg, n_reviews=1)
            .with_duration(total_dur)
            .with_effects([vfx.CrossFadeIn(CROSSFADE)])
            .with_start(start)
            .with_position("center")
        )
        return [clip]

    per_dur = total_dur / count
    clips = []
    for i in range(count):
        card = make_body_card([reviews[i]], font_bold, font_reg, n_reviews=1)
        clip = card.with_duration(per_dur)
        if i > 0:
            clip = clip.with_effects([vfx.CrossFadeIn(CROSSFADE)])
        clip = clip.with_start(start + i * (per_dur - CROSSFADE)).with_position("center")
        clips.append(clip)
    return clips


def _build_15s(
    business_name: str,
    rating: float,
    review_count: int,
    photo_paths: list[str],
    reviews: list[dict],
    output_path: str,
    fps: int,
    website_url: str,
    music_path: str | None,
    maps_url: str,
    music_offset: float,
    city: str,
    country: str,
    country_code: str,
    lat: float | None,
    lng: float | None,
    card_config: dict,
    font_bold: str,
    font_reg: str,
) -> None:
    ch = card_config.get("hook",  {})
    cb = card_config.get("body",  {})
    cp = card_config.get("proof", {})
    cc = card_config.get("cta",   {})

    include_hook  = bool(ch.get("enabled", True))
    include_body  = bool(cb.get("enabled", True))
    include_proof = bool(cp.get("enabled", True))
    include_cta   = bool(cc.get("enabled", True))

    hook_dur       = float(ch.get("duration", 2.0))
    body_dur       = float(cb.get("duration", 8.0))
    proof_dur      = float(cp.get("duration", 3.0))
    cta_dur        = float(cc.get("duration", 2.0))
    hook_variant   = ch.get("variant", "stars")
    n_reviews_body = int(cb.get("n_reviews", 1))
    cta_text       = cc.get("cta_text", "Réservez")
    social_handle  = cc.get("social_handle", "")
    show_qr        = bool(cc.get("show_qr", True))

    active_durs = []
    if include_hook:  active_durs.append(hook_dur)
    if include_body:  active_durs.append(body_dur)
    if include_proof: active_durs.append(proof_dur)
    if include_cta:   active_durs.append(cta_dur)
    n_transitions = max(0, len(active_durs) - 1)
    effective_total = max(sum(active_durs) - n_transitions * CROSSFADE, FADE * 2 + 1.0)

    n = min(len(photo_paths), 5)
    photos = random.sample(photo_paths, n)
    clip_dur = (effective_total + (n - 1) * CROSSFADE) / n

    photo_clips = []
    with _timer("ken_burns_clips"):
        for i, path in enumerate(photos):
            with _timer(f"ken_burns_clip_{i}"):
                clip = make_ken_burns_clip(path, clip_dur)
            if i > 0:
                clip = clip.with_effects([vfx.CrossFadeIn(CROSSFADE)])
            clip = clip.with_start(i * (clip_dur - CROSSFADE))
            photo_clips.append(clip)

    # Compute staggered segment start times
    cursor = 0.0
    hook_start = cursor
    if include_hook:  cursor += hook_dur - CROSSFADE
    body_start = cursor
    if include_body:  cursor += body_dur - CROSSFADE
    proof_start = cursor
    if include_proof: cursor += proof_dur - CROSSFADE
    cta_start = cursor

    cover_frame = None

    hook_clips: list = []
    if include_hook and reviews:
        with _timer("hook_card"):
            hc = make_hook_card(reviews[0], rating, font_bold, font_reg, variant=hook_variant)
            cover_frame = hc.get_frame(0)
            hc = (
                hc
                .with_duration(hook_dur)
                .with_effects([vfx.FadeOut(CROSSFADE)])
                .with_start(hook_start)
                .with_position("center")
            )
        hook_clips.append(hc)

    body_clips_list: list = []
    if include_body and reviews:
        with _timer("body_segment"):
            body_clips_list = _make_body_segment(
                reviews, font_bold, font_reg, body_start, body_dur, n_reviews_body,
            )

    proof_clips: list = []
    if include_proof:
        with _timer("proof_card"):
            pc = make_proof_card(business_name, rating, review_count, font_bold, font_reg)
            if cover_frame is None:
                cover_frame = pc.get_frame(0)
            pc = (
                pc
                .with_duration(proof_dur)
                .with_effects([vfx.CrossFadeIn(CROSSFADE)])
                .with_start(proof_start)
                .with_position("center")
            )
        proof_clips.append(pc)

    cta_clips: list = []
    if include_cta:
        _maps_url_arg = maps_url if show_qr else ""
        with _timer("cta_card"):
            ctac = make_cta_card(cta_text, _maps_url_arg, font_bold, font_reg, social_handle)
            if cover_frame is None:
                cover_frame = ctac.get_frame(0)
            ctac = (
                ctac
                .with_duration(cta_dur)
                .with_effects([vfx.CrossFadeIn(CROSSFADE)])
                .with_start(cta_start)
                .with_position("center")
            )
        cta_clips.append(ctac)

    all_clips = photo_clips + body_clips_list + proof_clips + hook_clips + cta_clips
    with _timer("composite"):
        final = (
            CompositeVideoClip(all_clips, size=(W, H))
            .with_duration(effective_total)
            .with_effects([vfx.FadeIn(FADE), vfx.FadeOut(FADE)])
        )

    if music_path:
        with _timer("audio_load"):
            audio = (
                AudioFileClip(music_path)
                .subclipped(music_offset, music_offset + effective_total)
                .with_effects([afx.AudioFadeIn(FADE), afx.AudioFadeOut(FADE)])
            )
        final = final.with_audio(audio)

    comment = f"Website: {website_url}" if website_url else "Generated by gmaps-reviews-short-video"
    metadata_params = [
        "-metadata", f"title={business_name}",
        "-metadata", "artist=gmaps-reviews-short-video",
        "-metadata", f"comment={comment}",
        "-metadata", f"year={datetime.date.today().year}",
    ]
    if lat is not None and lng is not None:
        location_str = f"{lat:+.6f}{lng:+.6f}/"
        metadata_params += ["-metadata", f"location={location_str}"]

    with _timer("prerender_frames"):
        n_frames = int(effective_total * fps)
        frame_times = np.linspace(0, effective_total - 1 / fps, n_frames)
        frames = [final.get_frame(t) for t in frame_times]
        prerendered = VideoClip(
            lambda t: frames[min(int(t * fps), n_frames - 1)],
            duration=effective_total,
        )
        if music_path:
            prerendered = prerendered.with_audio(final.audio)

    with _timer("ffmpeg_encode"):
        prerendered.write_videofile(
            output_path,
            fps=fps,
            codec="libx264",
            audio=music_path is not None,
            audio_codec="aac",
            preset="medium",
            threads=4,
            logger=None,
            ffmpeg_params=metadata_params,
        )
    with _timer("cover_embed"):
        _embed_cover_image(output_path, cover_frame)
    logger.info("saved: %s", output_path)

    if _timings:
        total_t = sum(t for _, t in _timings)
        lines = ["── Video generation timing ──────────────────"]
        for label, t in _timings:
            bar = "█" * int(t / total_t * 30) if total_t > 0 else ""
            lines.append(f"  {label:<26} {t:6.2f}s  {bar}")
        lines.append(f"  {'TOTAL':<26} {total_t:6.2f}s")
        lines.append("─────────────────────────────────────────────")
        logger.info("\n".join(lines))
        _timings.clear()


def build_video(
    business_name: str,
    rating: float,
    photo_paths: list[str],
    reviews: list[dict],
    output_path: str = "output.mp4",
    fps: int = 30,
    website_url: str = "",
    music_path: str | None = None,
    maps_url: str = "",
    music_offset: float = 0.0,
    city: str = "",
    country: str = "",
    country_code: str = "",
    lat: float | None = None,
    lng: float | None = None,
    card_config: dict | None = None,
    structure: str = "default",
    review_count: int = 0,
) -> None:
    with _timer("fonts"):
        font_bold = find_font()
        font_reg = find_font_regular()

    if not photo_paths:
        raise ValueError("No photos available to build video")

    if structure == "scenographie_15s":
        _build_15s(
            business_name=business_name,
            rating=rating,
            review_count=review_count,
            photo_paths=photo_paths,
            reviews=reviews,
            output_path=output_path,
            fps=fps,
            website_url=website_url,
            music_path=music_path,
            maps_url=maps_url,
            music_offset=music_offset,
            city=city,
            country=country,
            country_code=country_code,
            lat=lat,
            lng=lng,
            card_config=card_config or {},
            font_bold=font_bold,
            font_reg=font_reg,
        )
        return

    # --- Card configuration (per-card enable/duration/content toggles) ---
    cfg = card_config or {}
    ci = cfg.get("intro",  {})
    cr = cfg.get("review", {})
    cm = cfg.get("map",    {})
    co = cfg.get("outro",  {})

    include_intro  = bool(ci.get("enabled", True))
    include_review = bool(cr.get("enabled", True))
    include_map    = bool(cm.get("enabled", True))
    include_outro  = bool(co.get("enabled", True))
    show_qr        = bool(co.get("show_qr", True))
    show_website   = bool(co.get("show_website", True))

    title_dur = float(ci.get("duration", TITLE_DUR))
    map_dur   = float(cm.get("duration", MAP_DUR))
    outro_dur = float(co.get("duration", OUTRO_DUR))
    review_dur_cfg = float(cr["duration"]) if cr.get("duration") is not None else None

    # --- Map slide (requires lat/lng and enabled) ---
    with _timer("map_slide_render"):
        map_clip_raw = make_map_slide(lat, lng, business_name, city) if (include_map and lat and lng) else None
    has_map = map_clip_raw is not None

    # --- Compute effective total video length ---
    if review_dur_cfg is not None:
        # Sum active card durations, subtract crossfade overlaps between adjacent cards
        active_durs = []
        if include_intro:  active_durs.append(title_dur)
        if include_review: active_durs.append(review_dur_cfg)
        if has_map:        active_durs.append(map_dur)
        if include_outro:  active_durs.append(outro_dur)
        n_transitions = max(0, len(active_durs) - 1)
        effective_total = max(sum(active_durs) - n_transitions * CROSSFADE, FADE * 2 + 1.0)
    else:
        effective_total = TOTAL + (map_dur if has_map else 0)

    n = min(len(photo_paths), 5)
    photos = random.sample(photo_paths, n)

    # Each photo's visible duration so clips fill effective_total
    clip_dur = (effective_total + (n - 1) * CROSSFADE) / n

    # Build photo clips with Ken Burns + crossfade
    photo_clips = []
    with _timer("ken_burns_clips"):
        for i, path in enumerate(photos):
            with _timer(f"ken_burns_clip_{i}"):
                clip = make_ken_burns_clip(path, clip_dur)
            if i > 0:
                clip = clip.with_effects([vfx.CrossFadeIn(CROSSFADE)])
            start = i * (clip_dur - CROSSFADE)
            clip = clip.with_start(start)
            photo_clips.append(clip)

    # Title card — full-screen intro
    cover_frame = None
    title_clips: list = []
    if include_intro:
        with _timer("title_card"):
            tc_base = make_title_card(
                business_name, rating, font_bold, font_reg,
                photo_path=photos[0],
                city=city, country=country, country_code=country_code,
            )
            cover_frame = tc_base.get_frame(0)
            tc = (
                tc_base
                .with_duration(title_dur)
                .with_effects([vfx.FadeOut(CROSSFADE)])
                .with_start(0)
                .with_position("center")
            )
        title_clips.append(tc)

    # Single review card — fills the space between title and map/outro
    review_clips: list = []
    if reviews and include_review:
        review_start = (title_dur - CROSSFADE) if include_intro else 0.0
        if review_dur_cfg is not None:
            review_dur = review_dur_cfg
        else:
            review_end = effective_total - outro_dur - (map_dur if has_map else 0)
            review_dur = review_end - review_start

        with _timer("review_card"):
            rgb_arr, alpha_arr, card_h = make_review_card(reviews[0], font_reg, font_bold)
            card_clip = ImageClip(rgb_arr)
            mask_clip = ImageClip(alpha_arr, is_mask=True)
            card_clip = (
                card_clip
                .with_mask(mask_clip)
                .with_duration(review_dur)
                .with_effects([vfx.CrossFadeIn(CROSSFADE)])
                .with_start(review_start)
                .with_position((CARD_X, CARD_Y_BOT - card_h))
            )
        review_clips.append(card_clip)

    # Map slide — city context with business pinpoint, between review and outro
    map_clips: list = []
    if has_map:
        map_start = effective_total - outro_dur - map_dur
        map_slide = (
            map_clip_raw
            .with_duration(map_dur)
            .with_effects([vfx.CrossFadeIn(CROSSFADE)])
            .with_start(map_start)
            .with_position("center")
        )
        map_clips.append(map_slide)

    # Outro card — business name + URL + QR code
    outro_clips: list = []
    if include_outro:
        _website = website_url if show_website else ""
        _maps_url_arg = maps_url if show_qr else ""
        with _timer("outro_card"):
            oc = make_outro_card(business_name, _website, font_bold, font_reg, _maps_url_arg,
                                 city=city, country=country, country_code=country_code)
            oc = (
                oc
                .with_duration(outro_dur)
                .with_effects([vfx.CrossFadeIn(CROSSFADE)])
                .with_start(effective_total - outro_dur)
                .with_position("center")
            )
        outro_clips.append(oc)

    all_clips = photo_clips + review_clips + map_clips + title_clips + outro_clips
    with _timer("composite"):
        final = (
            CompositeVideoClip(all_clips, size=(W, H))
            .with_duration(effective_total)
            .with_effects([vfx.FadeIn(FADE), vfx.FadeOut(FADE)])
        )

    if music_path:
        with _timer("audio_load"):
            audio = (
                AudioFileClip(music_path)
                .subclipped(music_offset, music_offset + effective_total)
                .with_effects([afx.AudioFadeIn(FADE), afx.AudioFadeOut(FADE)])
            )
        final = final.with_audio(audio)

    comment = f"Website: {website_url}" if website_url else "Generated by gmaps-reviews-short-video"
    metadata_params = [
        "-metadata", f"title={business_name}",
        "-metadata", "artist=gmaps-reviews-short-video",
        "-metadata", f"comment={comment}",
        "-metadata", f"year={datetime.date.today().year}",
    ]
    if lat is not None and lng is not None:
        # ISO 6709 annex H format: ±DD.DDDD±DDD.DDDD/
        location_str = f"{lat:+.6f}{lng:+.6f}/"
        metadata_params += ["-metadata", f"location={location_str}"]

    # Pre-render all frames to RAM so ffmpeg encodes at full speed rather than
    # waiting on Python to generate each frame one-by-one.
    with _timer("prerender_frames"):
        n_frames = int(effective_total * fps)
        frame_times = np.linspace(0, effective_total - 1 / fps, n_frames)
        frames = [final.get_frame(t) for t in frame_times]
        prerendered = VideoClip(
            lambda t: frames[min(int(t * fps), n_frames - 1)],
            duration=effective_total,
        )
        if music_path:
            prerendered = prerendered.with_audio(final.audio)

    with _timer("ffmpeg_encode"):
        prerendered.write_videofile(
            output_path,
            fps=fps,
            codec="libx264",
            audio=music_path is not None,
            audio_codec="aac",
            preset="medium",
            threads=4,
            logger=None,
            ffmpeg_params=metadata_params,
        )
    with _timer("cover_embed"):
        _embed_cover_image(output_path, cover_frame)
    logger.info("saved: %s", output_path)

    if _timings:
        total_t = sum(t for _, t in _timings)
        lines = ["── Video generation timing ──────────────────"]
        for label, t in _timings:
            bar = "█" * int(t / total_t * 30) if total_t > 0 else ""
            lines.append(f"  {label:<26} {t:6.2f}s  {bar}")
        lines.append(f"  {'TOTAL':<26} {total_t:6.2f}s")
        lines.append("─────────────────────────────────────────────")
        logger.info("\n".join(lines))
        _timings.clear()
