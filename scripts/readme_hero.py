#!/usr/bin/env python3
# ruff: noqa: E501  (the hero is one block of inline HTML and CSS)
"""Compose the README hero, social preview and feature images from the raw README shots.

Run scripts/readme_shots.py first. This lays the real screenshots out with HTML and CSS,
renders them with Playwright, builds the approve-flow animated WebP, and writes docs/img/.
Needs the pngquant, optipng, ffmpeg and img2webp command-line tools (apt: pngquant optipng
ffmpeg webp) to optimise and animate; without them the PNGs are written unoptimised.

Usage: python scripts/readme_hero.py [SHOTS_DIR]   (default build/readme-shots)
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "img"

THEMES = {
    "light": {"bg": "#f5f5f7", "glow": "#ffffff", "ink": "#1d1d1f", "muted": "#6e6e73",
              "chip": "#ffffff", "chipink": "#1d1d1f", "line": "rgba(0,0,0,.08)",
              "shadow": "0 30px 60px -20px rgba(0,0,0,.25), 0 0 0 1px rgba(0,0,0,.06)"},
    "dark": {"bg": "#000000", "glow": "#1c1c1e", "ink": "#f5f5f7", "muted": "#a1a1a6",
             "chip": "#1c1c1e", "chipink": "#f5f5f7", "line": "rgba(255,255,255,.12)",
             "shadow": "0 30px 60px -20px rgba(0,0,0,.9), 0 0 0 1px rgba(255,255,255,.10)"},
}  # fmt: skip

HERO = """<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0}}
html,body{{width:1280px;height:640px;overflow:hidden}}
body{{font-family:Inter,"SF Pro Display",system-ui,sans-serif;color:{ink};
  background:radial-gradient(1200px 600px at 75% 30%,{glow} 0%,{bg} 60%);-webkit-font-smoothing:antialiased}}
.copy{{position:absolute;left:72px;top:0;bottom:0;width:400px;display:flex;flex-direction:column;justify-content:center}}
.mark{{display:flex;align-items:center;gap:12px;font-size:22px;font-weight:600;letter-spacing:-.01em}}
.mark i{{width:36px;height:36px;border-radius:50%;background:{ink};color:{bg};display:grid;place-items:center;
  font-style:normal;font-size:19px;font-weight:600}}
h1{{margin-top:28px;font-size:42px;line-height:1.1;font-weight:700;letter-spacing:-.035em}}
p{{margin-top:20px;font-size:18px;line-height:1.5;color:{muted};letter-spacing:-.005em}}
.chips{{margin-top:30px;display:flex;gap:8px;flex-wrap:wrap}}
.chips span{{font-size:13px;font-weight:500;padding:7px 13px;border-radius:999px;background:{chip};color:{chipink};
  box-shadow:0 0 0 1px {line}}}
.win{{position:absolute;left:610px;top:80px;width:860px;border-radius:14px;overflow:hidden;background:{chip};box-shadow:{shadow}}}
.bar{{height:30px;display:flex;align-items:center;gap:7px;padding:0 13px;border-bottom:1px solid {line}}}
.bar b{{width:11px;height:11px;border-radius:50%;background:{line}}}
.win img{{display:block;width:860px}}
.phone{{position:absolute;left:512px;top:236px;width:196px;padding:7px;border-radius:34px;background:#1d1d1f;box-shadow:{shadow}}}
.phone img{{display:block;width:182px;border-radius:27px}}
</style></head><body>
<div class="copy">
  <div class="mark"><i>b</i>brandcal</div>
  <h1>Your AI agents draft. You approve every post.</h1>
  <p>An open-source content calendar with a strict CLI, a calm web UI and a tamper-evident audit log. Self-host it free on Cloudflare.</p>
  <div class="chips"><span>Human approval</span><span>Agent-ready CLI</span><span>Cloudflare Workers + D1</span><span>MIT</span></div>
</div>
<div class="win"><div class="bar"><b></b><b></b><b></b></div><img src="{desk}" alt=""></div>
<div class="phone"><img src="{phone}" alt=""></div>
</body></html>"""


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def flow(frames: Path, target: Path) -> None:
    """Scale the approve-flow frames to 1200px and join them; each name ends in its hold time."""
    if not frames.is_dir() or not (shutil.which("ffmpeg") and shutil.which("img2webp")):
        return
    args: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for png in sorted(frames.glob("*.png")):
            small = Path(tmp) / png.name
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(png), "-vf",
                            "scale=1200:-1:flags=lanczos", str(small)], check=True)  # fmt: skip
            args += ["-d", png.stem.split("-")[1], str(small)]
        subprocess.run(["img2webp", "-loop", "0", "-lossy", "-q", "82", "-m", "6", *args,
                        "-o", str(target)], check=True, capture_output=True)  # fmt: skip


def main(argv: list[str]) -> int:
    shots = Path(argv[0]) if argv else ROOT / "build" / "readme-shots"
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme, colours in THEMES.items():
            html = HERO.format(
                desk=data_uri(shots / f"calendar-week-{theme}.png"),
                phone=data_uri(shots / f"mobile-week-{theme}.png"),
                **colours,
            )
            for scale, name in ((2, f"hero-{theme}.png"), (1, f"social-preview-{theme}.png")):
                page = browser.new_page(
                    viewport={"width": 1280, "height": 640}, device_scale_factor=scale
                )
                page.set_content(html)
                page.wait_for_timeout(300)
                page.screenshot(path=str(OUT / name))
                page.close()
        browser.close()
    shutil.copy(OUT / "social-preview-light.png", OUT / "social-preview.png")
    (OUT / "social-preview-light.png").unlink()
    # README name -> raw shot name
    keep = {"calendar-month": "calendar-month",
            "post-panel": "post-panel-pending", "needs-you": "needs-you", "activity": "activity",
            "mobile-week": "mobile-week"}  # fmt: skip
    for name, raw in keep.items():
        for theme in THEMES:
            shutil.copy(shots / f"{raw}-{theme}.png", OUT / f"{name}-{theme}.png")
    flow(shots / "approve-flow", OUT / "approve-flow.webp")
    written = [OUT / "social-preview.png", OUT / "social-preview-dark.png"]
    written += [OUT / f"hero-{t}.png" for t in THEMES]
    written += [OUT / f"{n}-{t}.png" for n in keep for t in THEMES]
    if shutil.which("pngquant") and shutil.which("optipng"):
        for path in written:
            subprocess.run(["pngquant", "--quality", "70-92", "--speed", "1", "--strip",
                            "--force", "--ext", ".png", str(path)], check=True)  # fmt: skip
            subprocess.run(["optipng", "-quiet", "-o2", "-strip", "all", str(path)], check=True)
    print(f"images written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
