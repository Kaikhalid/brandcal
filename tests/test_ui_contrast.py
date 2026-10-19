"""The UI colour tokens meet WCAG 2.2 AA, computed from web/app/globals.css (docs/UI_STYLE.md)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "web" / "app" / "globals.css"
PLATFORMS = ("linkedin", "x", "instagram", "youtube", "bluesky")
STATUSES = ("draft", "awaiting", "scheduled", "published", "failed")


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ui_contrast", ROOT / "scripts/ui_contrast.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses looks its module up here
    spec.loader.exec_module(module)
    return module


uc = load_script()


def test_the_maths_matches_the_wcag_definition() -> None:
    assert uc.contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert uc.contrast((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.01)
    assert uc.contrast((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)


def test_hex_colours_parse_with_alpha_and_flatten_over_a_backdrop() -> None:
    assert uc.parse_colour("#fff") == (255, 255, 255, 1.0)
    assert uc.parse_colour("#102030") == (16, 32, 48, 1.0)
    r, g, b, a = uc.parse_colour("#00000080")
    assert (r, g, b) == (0, 0, 0) and a == pytest.approx(0.502, abs=0.001)
    assert uc.flatten((0, 0, 0, 0.5), (255, 255, 255)) == (128, 128, 128)
    with pytest.raises(ValueError):
        uc.parse_colour("oklch(0.5 0 0)")


def test_tokens_resolve_var_references_and_dark_inherits_light() -> None:
    css = ":root {\n--a: #111111; --b: var(--a); --c: #ffffff;\n}\n.dark {\n--a: #eeeeee;\n}\n"
    tokens = uc.parse_tokens(css)
    assert uc.resolve(tokens["light"], "b") == (17, 17, 17, 1.0)
    assert uc.resolve(tokens["dark"], "b") == (238, 238, 238, 1.0)
    assert uc.resolve(tokens["dark"], "c") == (255, 255, 255, 1.0)


def test_every_pair_passes_in_both_themes() -> None:
    rows = uc.evaluate(CSS.read_text(encoding="utf-8"))
    failures = [r.describe() for r in rows if not r.ok]
    assert not failures, "\n" + "\n".join(failures)
    assert {r.theme for r in rows} == {"light", "dark"}


def test_the_minimums_are_the_wcag_ones() -> None:
    rows = uc.evaluate(CSS.read_text(encoding="utf-8"))
    assert {r.minimum for r in rows if r.kind == "text"} == {4.5}
    non_text = {"boundary", "focus", "chip-icon", "state"}
    assert {r.minimum for r in rows if r.kind in non_text} == {3.0}


def test_the_checks_cover_every_platform_and_status_in_both_themes() -> None:
    rows = uc.evaluate(CSS.read_text(encoding="utf-8"))
    for theme in ("light", "dark"):
        names = {r.name for r in rows if r.theme == theme}
        for platform in PLATFORMS:
            assert f"platform {platform} text" in names, (theme, platform)
        for status in STATUSES:
            assert f"status {status} text" in names, (theme, status)
            assert f"status {status} icon" in names, (theme, status)
        assert {"control boundary", "focus ring", "black pill text"} <= {
            n for n in names if not n.startswith(("platform", "status"))
        }


def test_glass_text_is_checked_over_the_canvas_the_card_and_every_pastel() -> None:
    rows = uc.evaluate(CSS.read_text(encoding="utf-8"))
    glass = {r.name for r in rows if r.name.startswith("glass ink")}
    assert len(glass) >= 2 + len(PLATFORMS)


def test_a_low_contrast_token_fails_the_gate() -> None:
    css = CSS.read_text(encoding="utf-8").replace("--label: #", "--label: #cccccc; --x: #", 1)
    rows = uc.evaluate(css)
    assert any(not r.ok and "label" in r.name for r in rows)
    assert uc.main([str(CSS)]) == 0


def test_published_is_a_solid_fill_unlike_the_ink_pill() -> None:
    tokens = uc.parse_tokens(CSS.read_text(encoding="utf-8"))
    for theme in ("light", "dark"):
        pub = uc.resolve(tokens[theme], "st-published-bg")
        assert pub != uc.resolve(tokens[theme], "pill-bg")
        assert pub != uc.resolve(tokens[theme], "ink")
        assert uc.contrast(pub[:3], uc.resolve(tokens[theme], "canvas")[:3]) >= 3.0
