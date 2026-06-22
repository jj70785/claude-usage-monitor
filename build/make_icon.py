"""Generate assets/icon.ico — a clean 'usage gauge' app logo (blue ring + dot).
Distinct from the dynamic tray icon (which shows the live %)."""
import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "icon.ico")
RING = (74, 158, 255, 255)
TRACK = (60, 61, 64, 255)
DOT = (232, 234, 237, 255)


def gauge(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, int(size * 0.13))
    width = max(2, int(size * 0.13))
    box = (pad, pad, size - pad, size - pad)
    d.arc(box, 0, 360, fill=TRACK, width=width)
    d.arc(box, -90, -90 + int(0.68 * 360), fill=RING, width=width)
    r = max(1, int(size * 0.07))
    c = size / 2
    d.ellipse((c - r, c - r, c + r, c + r), fill=DOT)
    return img


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    sizes = [256, 128, 64, 48, 32, 16]
    base = gauge(256)
    base.save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print("wrote", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
