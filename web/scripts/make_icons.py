"""Regenerate the app icons: python3 web/scripts/make_icons.py (needs Pillow).

Obsidian square with a warm stone calendar and a check. iOS rounds the corners itself,
so the square is full bleed and opaque.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OBSIDIAN = (18, 19, 22)
STONE = (246, 244, 240)
SIZE = 1024 * 4  # drawn large, then scaled down for smooth edges
U = SIZE / 1024
WEB = Path(__file__).resolve().parent.parent


def box(x0: float, y0: float, x1: float, y1: float) -> list[float]:
    return [x0 * U, y0 * U, x1 * U, y1 * U]


def main() -> None:
    im = Image.new("RGB", (SIZE, SIZE), OBSIDIAN)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(box(232, 276, 792, 800), radius=72 * U, fill=STONE)
    d.rectangle(box(232, 400, 792, 428), fill=OBSIDIAN)  # header divider
    for x in (372, 652):  # binder rings, with a dark halo so they read at small sizes
        d.rounded_rectangle(box(x - 46, 196, x + 46, 352), radius=46 * U, fill=OBSIDIAN)
        d.rounded_rectangle(box(x - 24, 214, x + 24, 334), radius=24 * U, fill=STONE)
    pts = [(392, 612), (482, 698), (640, 530)]
    d.line([(x * U, y * U) for x, y in pts], fill=OBSIDIAN, width=int(64 * U), joint="curve")
    for x, y in (pts[0], pts[-1]):
        d.ellipse(box(x - 32, y - 32, x + 32, y + 32), fill=OBSIDIAN)
    big = im.resize((1024, 1024), Image.LANCZOS)
    for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
        big.resize((size, size), Image.LANCZOS).save(WEB / "public" / name, optimize=True)
    small = big.convert("RGBA").resize((48, 48), Image.LANCZOS)
    small.save(WEB / "app" / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])


if __name__ == "__main__":
    main()
