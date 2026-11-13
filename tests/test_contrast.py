"""WCAG 2 contrast of the colour tokens in app.css, both themes (UI_SPEC 6)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from brandcal import serve

CSS = (Path(serve.__file__).parent / "web" / "app.css").read_text(encoding="utf-8")
STATES = ["pending", "changes", "approved", "missed", "published", "cancelled"]
Rgb = tuple[float, float, float]


def block(selector: str) -> dict[str, str]:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, selector
    return dict(re.findall(r"(--[a-z-]+)\s*:\s*([^;]+);", match.group(1)))


def parse(value: str, under: Rgb | None = None) -> Rgb:
    """#rrggbb, or rgba() composited over ``under``."""
    value = value.strip()
    if value.startswith("#"):
        return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
    nums = [float(n) for n in re.findall(r"[\d.]+", value)]
    assert value.startswith("rgba") and under is not None, value
    alpha = nums[3]
    return tuple(alpha * nums[i] + (1 - alpha) * under[i] for i in range(3))  # type: ignore[return-value]


def luminance(rgb: Rgb) -> float:
    lin = [
        c / 255 / 12.92 if c / 255 <= 0.03928 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb
    ]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: Rgb, b: Rgb) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


THEMES = {"light": block(":root"), "dark": block(':root[data-theme="dark"]')}


@pytest.fixture(params=sorted(THEMES))
def tokens(request: pytest.FixtureRequest) -> dict[str, str]:
    return THEMES[request.param]


def solid(tokens: dict[str, str], name: str) -> Rgb:
    return parse(tokens[name])


def surfaces(tokens: dict[str, str]) -> dict[str, Rgb]:
    """Every background text can sit on: page, card, solid panel and glass over page or card."""
    bg, card, panel = (solid(tokens, n) for n in ("--bg", "--card", "--panel-solid"))
    return {
        "bg": bg,
        "card": card,
        "panel-solid": panel,
        "glass-on-bg": parse(tokens["--panel-glass"], bg),
        "glass-on-card": parse(tokens["--panel-glass"], card),
    }


def test_both_themes_define_the_same_tokens() -> None:
    assert set(THEMES["light"]) == set(THEMES["dark"])
    for name in ("--bg", "--card", "--panel-solid", "--panel-glass", "--ink", "--ink-muted"):
        assert name in THEMES["light"] and name in THEMES["dark"]
    for state in STATES:
        assert f"--st-{state}" in THEMES["light"] and f"--st-{state}" in THEMES["dark"]


@pytest.mark.parametrize("text", ["--ink", "--ink-muted", "--accent"])
def test_text_is_4_5_to_1_on_every_surface(tokens: dict[str, str], text: str) -> None:
    for name, surface in surfaces(tokens).items():
        assert ratio(solid(tokens, text), surface) >= 4.5, (text, name)


@pytest.mark.parametrize("state", STATES)
def test_each_status_colour_is_4_5_to_1_on_every_surface(
    tokens: dict[str, str], state: str
) -> None:
    for name, surface in surfaces(tokens).items():
        assert ratio(solid(tokens, f"--st-{state}"), surface) >= 4.5, (state, name)


def test_ui_parts_are_3_to_1(tokens: dict[str, str]) -> None:
    for name in ("--ring", "--control-line"):
        for surface_name, surface in surfaces(tokens).items():
            assert ratio(solid(tokens, name), surface) >= 3.0, (name, surface_name)


def test_the_error_and_banner_colours_pass(tokens: dict[str, str]) -> None:
    assert ratio(solid(tokens, "--danger-ink"), solid(tokens, "--danger-bg")) >= 4.5
    for name in ("--card", "--bg", "--panel-solid"):
        assert ratio(solid(tokens, "--danger-text"), solid(tokens, name)) >= 4.5
    assert ratio(solid(tokens, "--accent-ink"), solid(tokens, "--accent-fill")) >= 4.5


def test_the_light_theme_keeps_the_spec_values() -> None:
    light = THEMES["light"]
    expected = {
        "--bg": "#F4F6FA",
        "--panel-solid": "#FFFFFF",
        "--ink": "#0F172A",
        "--ink-muted": "#475569",
        "--accent": "#1D4ED8",
        "--st-pending": "#92400E",
        "--st-changes": "#B91C1C",
        "--st-approved": "#166534",
        "--st-missed": "#6B21A8",
        "--st-published": "#1E40AF",
        "--st-cancelled": "#475569",
    }
    for name, value in expected.items():
        assert light[name].upper() == value, name
    assert light["--panel-glass"].replace(" ", "") == "rgba(255,255,255,0.72)"
