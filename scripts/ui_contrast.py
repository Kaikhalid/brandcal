#!/usr/bin/env python3
"""Compute WCAG 2.2 contrast ratios from the colour tokens in web/app/globals.css.

Reads the `:root` (light) and `.dark` blocks, resolves `var(--x)` references, flattens
translucent colours over the backdrop they sit on, and checks every pair listed in
docs/UI_STYLE.md: 4.5:1 for text, 3:1 for control boundaries, focus rings, the black pill's
state cue and status chip icons. Tokens must be hex (`#rgb`, `#rrggbb`, `#rrggbbaa`) so
this script needs nothing beyond the standard library.

Usage: python scripts/ui_contrast.py [GLOBALS_CSS]
Exit status: 0 if every pair passes, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CSS = Path(__file__).resolve().parent.parent / "web" / "app" / "globals.css"
PLATFORMS = ("linkedin", "x", "instagram", "youtube", "bluesky")
STATUSES = ("draft", "awaiting", "scheduled", "published", "failed")
TEXT, NON_TEXT = 4.5, 3.0

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, float]
Tokens = dict[str, str]


def parse_colour(value: str) -> RGBA:
    """A hex colour as (r, g, b, alpha)."""
    match = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", value.strip())
    if not match:
        raise ValueError(f"not a hex colour: {value!r}")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    r, g, b = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
    alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
    return r, g, b, alpha


def flatten(fg: RGBA, backdrop: RGB) -> RGB:
    """`fg` composited over an opaque backdrop."""
    r, g, b, a = fg
    mixed = (round(a * c + (1 - a) * k) for c, k in zip((r, g, b), backdrop, strict=True))
    out = tuple(mixed)
    return out[0], out[1], out[2]


def luminance(rgb: RGB) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: RGB, bg: RGB) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _declarations(css: str, selector: str) -> Tokens:
    block = re.search(rf"^{re.escape(selector)}\s*\{{(.*?)^\}}", css, re.S | re.M)
    if not block:
        raise ValueError(f"no {selector} block in the stylesheet")
    return dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block.group(1)))


def parse_tokens(css: str) -> dict[str, Tokens]:
    """Light and dark token maps; dark inherits whatever it does not override."""
    light = _declarations(css, ":root")
    return {"light": light, "dark": {**light, **_declarations(css, ".dark")}}


def resolve(tokens: Tokens, name: str, depth: int = 0) -> RGBA:
    if name not in tokens:
        raise KeyError(f"unknown token --{name}")
    value = tokens[name].strip()
    ref = re.fullmatch(r"var\(--([\w-]+)\)", value)
    if ref and depth < 8:
        return resolve(tokens, ref.group(1), depth + 1)
    return parse_colour(value)


@dataclass(frozen=True)
class Row:
    theme: str
    name: str
    kind: str  # text | boundary | focus | chip-icon | state
    fg: str
    bg: str
    ratio: float
    minimum: float

    @property
    def ok(self) -> bool:
        return self.ratio + 1e-9 >= self.minimum

    def describe(self) -> str:
        verdict = "pass" if self.ok else "FAIL"
        return (
            f"{verdict}  {self.theme:<5}  {self.ratio:5.2f}:1 (min {self.minimum})"
            f"  {self.name}  [{self.fg} on {self.bg}]"
        )


def evaluate(css: str) -> list[Row]:
    rows: list[Row] = []
    for theme, tokens in parse_tokens(css).items():

        def solid(name: str, tokens: Tokens = tokens) -> RGB:
            r, g, b, _ = resolve(tokens, name)
            return r, g, b

        def pair(
            name: str, kind: str, fg: str, bg: str, minimum: float,
            theme: str = theme, solid: Callable[[str], RGB] = solid,
        ) -> None:  # fmt: skip
            rows.append(Row(theme, name, kind, fg, bg, contrast(solid(fg), solid(bg)), minimum))

        pair("ink on canvas", "text", "ink", "canvas", TEXT)
        pair("ink on surface", "text", "ink", "surface", TEXT)
        pair("label on canvas", "text", "label", "canvas", TEXT)
        pair("label on surface", "text", "label", "surface", TEXT)
        pair("label on muted", "text", "label", "muted-fill", TEXT)
        pair("ink on muted", "text", "ink", "muted-fill", TEXT)
        pair("destructive on canvas", "text", "destructive", "canvas", TEXT)
        pair("destructive on surface", "text", "destructive", "surface", TEXT)
        pair("control boundary", "boundary", "control-boundary", "canvas", NON_TEXT)
        pair("control boundary on surface", "boundary", "control-boundary", "surface", NON_TEXT)
        pair("focus ring", "focus", "focus-ring", "canvas", NON_TEXT)
        pair("focus ring on surface", "focus", "focus-ring", "surface", NON_TEXT)
        pair("black pill text", "text", "pill-fg", "pill-bg", TEXT)
        pair("black pill against canvas", "state", "pill-bg", "canvas", NON_TEXT)

        backdrops = {"canvas": "canvas", "surface": "surface"}
        for platform in PLATFORMS:
            ink, bg = f"pf-{platform}-ink", f"pf-{platform}-bg"
            pair(f"platform {platform} text", "text", ink, bg, TEXT)
            backdrops[platform] = bg
        for status in STATUSES:
            bg = f"st-{status}-bg"
            pair(f"status {status} text", "text", f"st-{status}-ink", bg, TEXT)
            pair(f"status {status} icon", "chip-icon", f"st-{status}-ink", bg, NON_TEXT)

        # Glass sits on the shell only, over whatever scrolls beneath it: check text on the
        # translucent fill flattened over each backdrop it can meet.
        glass = resolve(tokens, "glass")
        for label_name, backdrop in backdrops.items():
            flat = flatten(glass, solid(backdrop))
            for ink in ("ink", "label"):
                ratio = contrast(solid(ink), flat)
                name = f"glass {ink} over {label_name}"
                rows.append(Row(theme, name, "text", ink, "glass", ratio, TEXT))
        pair("glass fallback ink", "text", "ink", "glass-solid", TEXT)
        pair("glass fallback label", "text", "label", "glass-solid", TEXT)
    return rows


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else DEFAULT_CSS
    rows = evaluate(path.read_text(encoding="utf-8"))
    for row in rows:
        print(row.describe())
    failed = [r for r in rows if not r.ok]
    if failed:
        print(f"ui contrast: {len(failed)} of {len(rows)} pair(s) fail", file=sys.stderr)
        return 1
    print(f"ui contrast: all {len(rows)} pairs pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
