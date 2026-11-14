"""Rebuild the app icons from the source artwork (needs Pillow and numpy).

    python3 web/scripts/make_icons.py path/to/artwork-1024.png

The artwork is a rounded-square icon on a transparent background. iOS applies its own
rounded mask, so the calendar is cut out and placed on a purple-to-blue fill that runs into
every corner: full bleed, opaque, no bezel. The maskable icon keeps the calendar inside the
central 80% safe zone.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

WEB = Path(__file__).resolve().parent.parent
CX, CY = 513, 507  # calendar centre in the 1024px artwork


def calendar_mask() -> Image.Image:
    """The calendar shape in artwork pixels, slightly generous for its outline glow."""
    m = Image.new("L", (1024, 1024), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([224, 264, 801, 414], radius=46, fill=255)
    d.rounded_rectangle([224, 418, 802, 810], radius=50, fill=255)
    d.rectangle([228, 400, 798, 430], fill=255)
    for x0, x1 in ((334, 416), (614, 694)):
        d.rounded_rectangle([x0, 204, x1, 344], radius=41, fill=255)
    return m.filter(ImageFilter.GaussianBlur(2.5))


def background(n: int) -> Image.Image:
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) / (n - 1)
    t = np.clip((xx + (1 - yy)) / 2, 0, 1)[..., None]  # 0 bottom-left, 1 top-right
    purple = np.array([78, 36, 170], np.float32)
    blue = np.array([70, 120, 235], np.float32)
    deep = np.array([48, 20, 110], np.float32)
    shade = 0.35 * (yy[..., None] ** 2)
    bg = (purple * (1 - t) + blue * t) * (1 - shade) + deep * shade
    sheen = np.exp(-(((xx - yy) - 0.35) ** 2) / 0.01)[..., None] * (1 - yy[..., None]) * 18
    return Image.fromarray(np.clip(bg + sheen, 0, 255).astype(np.uint8))


def render(art: Image.Image, half: int) -> Image.Image:
    box = (CX - half, CY - half, CX + half, CY + half)
    fg = art.crop(box)
    fm = calendar_mask().crop(box)
    n = fg.size[0]
    shadow = Image.new("L", (n, n), 0)
    shadow.paste(fm, (0, 14))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22)).point(lambda v: int(v * 0.55))
    bg = Image.composite(Image.new("RGB", (n, n), (20, 8, 50)), background(n), shadow)
    return Image.composite(fg, bg, fm).resize((1024, 1024), Image.LANCZOS)


def palette(im: Image.Image) -> Image.Image:
    method, dither = Image.Quantize.MEDIANCUT, Image.Dither.FLOYDSTEINBERG
    return im.quantize(colors=256, method=method, dither=dither)


def main(source: str) -> None:
    art = Image.open(source).convert("RGBA").convert("RGB")
    icon, maskable = render(art, 400), render(art, 560)
    public = WEB / "public"
    icon.resize((180, 180), Image.LANCZOS).save(public / "apple-touch-icon.png", optimize=True)
    icon.resize((192, 192), Image.LANCZOS).save(public / "icon-192.png", optimize=True)
    palette(icon.resize((512, 512), Image.LANCZOS)).save(public / "icon-512.png", optimize=True)
    small = palette(maskable.resize((512, 512), Image.LANCZOS))
    small.save(public / "icon-maskable-512.png", optimize=True)
    fav = icon.convert("RGBA").resize((48, 48), Image.LANCZOS)
    fav.save(WEB / "app" / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])


if __name__ == "__main__":
    main(sys.argv[1])
