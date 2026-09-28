"""Tray icon rendering (Pillow), shared by the Linux, Windows and macOS trays.

One icon per AI: a ring whose arc fills with the provider's most-used limit, colored
green -> yellow -> red, with that percentage in the middle. The ring's track carries a
faint provider tint so several icons side by side stay tellable apart.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from . import config

PROVIDER_TINT = {
    "claude": (74, 48, 40),      # dim Claude orange
    "codex": (62, 62, 68),       # dim neutral gray
    "gemini": (40, 52, 88),      # dim Gemini blue
}
DEFAULT_TINT = (62, 62, 68)
NO_DATA = (150, 150, 156)

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


@lru_cache(maxsize=16)
def _font(px: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:                      # Pillow < 10.1
        return ImageFont.load_default()


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ring_image(percent: Optional[float], provider_id: str = "", size: int = 64,
               stale: bool = False) -> Image.Image:
    """Ring gauge + centered number. `percent=None` draws an empty ring with a dash."""
    scale = 4                               # supersample for smooth edges at tray sizes
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    width = int(s * 0.14)
    pad = width // 2 + scale
    box = (pad, pad, s - pad, s - pad)
    track = PROVIDER_TINT.get(provider_id.split(":")[0], DEFAULT_TINT)
    d.arc(box, 0, 360, fill=track + (255,), width=width)

    if percent is None:
        text, fg = "–", NO_DATA
    else:
        p = max(0.0, float(percent))
        color = _hex_to_rgb(config.color_for_percent(p))
        if stale:
            gray = sum(color) // 3
            color = tuple(int(c * 0.25 + gray * 0.35) for c in color)   # grayed out = old data
        if p > 0:
            d.arc(box, -90, -90 + min(p, 100.0) / 100.0 * 360, fill=color + (255,), width=width)
        text = "!!" if p >= 100 else f"{p:.0f}"
        fg = (240, 240, 244) if not stale else (175, 175, 180)

    font_px = int(s * (0.40 if len(text) <= 2 else 0.32))
    font = _font(font_px)
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((s - tw) / 2 - bbox[0], (s - th) / 2 - bbox[1]), text, font=font, fill=fg + (255,),
           stroke_width=max(1, scale // 2), stroke_fill=(20, 20, 24, 200))
    return img.resize((size, size), Image.LANCZOS)
