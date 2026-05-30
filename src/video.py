import datetime
import os
import textwrap

import numpy as np
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
TOTAL = 7.0
CROSSFADE = 0.5
FADE = 0.5       # global fade-in from black / fade-to-black duration
OUTRO_DUR = 2.0  # seconds the outro card is visible before the video ends
HEADER_H = 150
CARD_H = 420
CARD_MARGIN = 40


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


def make_review_card(review: dict, font_path: str, font_bold_path: str) -> tuple[np.ndarray, np.ndarray]:
    card = Image.new("RGBA", (W, CARD_H), (0, 0, 0, 0))
    bg = Image.new("RGBA", (W, CARD_H), (15, 15, 15, 210))
    card.paste(bg, (0, 0))
    draw = ImageDraw.Draw(card)

    pad = 48
    y = 36

    # Star rating + author line
    stars = "★" * int(review["rating"]) + "☆" * (5 - int(review["rating"]))
    author = review["author"] or "Customer"
    header_text = f"{stars}  {author}"
    try:
        hfont = ImageFont.truetype(font_bold_path, 34)
    except Exception:
        hfont = ImageFont.load_default()
    draw.text((pad, y), header_text, font=hfont, fill=(255, 210, 50, 255))
    y += 52

    # Divider
    draw.line([(pad, y), (W - pad, y)], fill=(255, 255, 255, 60), width=1)
    y += 20

    # Review text (word-wrapped)
    text = review["text"]
    if len(text) > 240:
        text = text[:237] + "…"

    try:
        rfont = ImageFont.truetype(font_path, 36)
    except Exception:
        rfont = ImageFont.load_default()

    # Wrap text to fit within card width
    max_chars = 42
    lines = textwrap.wrap(text, width=max_chars)
    max_lines = 6
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "…"

    for line in lines:
        draw.text((pad, y), line, font=rfont, fill=(240, 240, 240, 255))
        y += 46

    alpha = np.array(card.split()[3]).astype(float) / 255.0
    return np.array(card.convert("RGB")), alpha


def make_outro_card(
    business_name: str, website_url: str, font_bold: str, font_reg: str
) -> ImageClip:
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

    name_lines = textwrap.wrap(business_name, width=20) or [business_name]
    line_h = 80
    has_url = bool(website_url)
    total_text_h = len(name_lines) * line_h + (60 if has_url else 0)
    text_top = (H - total_text_h) // 2

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

    alpha = np.array(frame.split()[3]).astype(float) / 255.0
    rgb = np.array(frame.convert("RGB"))
    clip = ImageClip(rgb)
    mask = ImageClip(alpha, is_mask=True)
    return clip.with_mask(mask)


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
) -> None:
    font_bold = find_font()
    font_reg = find_font_regular()

    if not photo_paths:
        raise ValueError("No photos available to build video")

    n = min(len(photo_paths), 5)
    photos = photo_paths[:n]

    # Each photo's visible duration so total = TOTAL seconds
    # With crossfades: total = n * clip_dur - (n-1) * CROSSFADE
    clip_dur = (TOTAL + (n - 1) * CROSSFADE) / n

    # Build photo clips with Ken Burns + crossfade
    photo_clips = []
    for i, path in enumerate(photos):
        clip = make_ken_burns_clip(path, clip_dur)
        if i > 0:
            clip = clip.with_effects([vfx.CrossFadeIn(CROSSFADE)])
        start = i * (clip_dur - CROSSFADE)
        clip = clip.with_start(start)
        photo_clips.append(clip)

    # Header overlay
    header_clips = make_header(business_name, rating, font_bold)

    # Review cards — one per ~(TOTAL/n_reviews) seconds
    review_clips = []
    if reviews:
        n_reviews = min(len(reviews), n)
        review_dur = TOTAL / n_reviews
        for i, review in enumerate(reviews[:n_reviews]):
            rgb_arr, alpha_arr = make_review_card(review, font_reg, font_bold)

            # Build clip with alpha mask
            card_clip = ImageClip(rgb_arr)
            mask_clip = ImageClip(alpha_arr, is_mask=True)
            card_clip = card_clip.with_mask(mask_clip)

            start = i * review_dur
            remaining = TOTAL - start
            dur = min(review_dur, remaining)

            fade_in = min(CROSSFADE, dur / 2)
            card_clip = (
                card_clip
                .with_duration(dur)
                .with_effects([vfx.CrossFadeIn(fade_in)])
                .with_start(start)
                .with_position((0, H - CARD_H - CARD_MARGIN))
            )
            review_clips.append(card_clip)

    # Outro card — business name + URL, visible for the last OUTRO_DUR seconds
    outro_clip = make_outro_card(business_name, website_url, font_bold, font_reg)
    outro_clip = (
        outro_clip
        .with_duration(OUTRO_DUR)
        .with_effects([vfx.CrossFadeIn(CROSSFADE)])
        .with_start(TOTAL - OUTRO_DUR)
        .with_position("center")
    )

    all_clips = photo_clips + header_clips + review_clips + [outro_clip]
    final = (
        CompositeVideoClip(all_clips, size=(W, H))
        .with_duration(TOTAL)
        .with_effects([vfx.FadeIn(FADE), vfx.FadeOut(FADE)])
    )

    if music_path:
        audio = (
            AudioFileClip(music_path)
            .subclipped(0, TOTAL)
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
