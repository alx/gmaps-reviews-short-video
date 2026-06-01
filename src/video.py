import datetime
import os
import random
import textwrap

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
        qr_img = qrcode.make(maps_url).convert("RGBA").resize(
            (QR_SIZE, QR_SIZE), Image.Resampling.LANCZOS
        )
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
        _draw_mixed_text(frame, draw, cta_y, "📤 Share this QR Code",
                         cta_font, emoji_fp, (150, 150, 150, 255), CTA_LINE_H, W)

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
        print(f"  Warning: map slide skipped ({exc})")
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
) -> None:
    font_bold = find_font()
    font_reg = find_font_regular()

    if not photo_paths:
        raise ValueError("No photos available to build video")

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
    for i, path in enumerate(photos):
        clip = make_ken_burns_clip(path, clip_dur)
        if i > 0:
            clip = clip.with_effects([vfx.CrossFadeIn(CROSSFADE)])
        start = i * (clip_dur - CROSSFADE)
        clip = clip.with_start(start)
        photo_clips.append(clip)

    # Title card — full-screen intro
    title_clips: list = []
    if include_intro:
        tc = (
            make_title_card(business_name, rating, font_bold, font_reg,
                            photo_path=photos[0],
                            city=city, country=country, country_code=country_code)
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
    final = (
        CompositeVideoClip(all_clips, size=(W, H))
        .with_duration(effective_total)
        .with_effects([vfx.FadeIn(FADE), vfx.FadeOut(FADE)])
    )

    if music_path:
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
    final.write_videofile(
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
    print(f"  Saved: {output_path}")
