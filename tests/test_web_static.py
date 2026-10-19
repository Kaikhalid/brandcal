"""Static assets served by `brandcal serve` (UI_SPEC 2.1, 2.7, 6) and the generic 500 handler."""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from ui_env import make_home

from brandcal import actions, serve
from brandcal.config import load_config

WEB = Path(serve.__file__).parent / "web"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/theme.js": ("theme.js", "text/javascript; charset=utf-8"),
    "/icons.svg": ("icons.svg", "image/svg+xml"),
}
# The SVG namespace is an identifier, not a request.
NAMESPACE = "http://www.w3.org/2000/svg"


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    raw: bytes


class Client:
    def __init__(self, port: int) -> None:
        self.port = port

    def call(self, method: str, path: str) -> Resp:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path)
            res = conn.getresponse()
            return Resp(res.status, {k.lower(): v for k, v in res.getheaders()}, res.read())
        finally:
            conn.close()

    def get(self, path: str) -> Resp:
        return self.call("GET", path)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Client]:
    home = make_home(tmp_path / "home", monkeypatch)
    server = serve.make_server(home, load_config(home), 0, None, dev=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield Client(server.server_address[1])
    server.shutdown()
    server.server_close()


def text(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("path", sorted(ASSETS))
def test_assets_are_served_with_their_type_and_hardening_headers(client: Client, path: str) -> None:
    name, ctype = ASSETS[path]
    res = client.get(path)
    assert res.status == 200 and res.raw == (WEB / name).read_bytes()
    assert res.headers["content-type"] == ctype
    assert res.headers["content-security-policy"] == "default-src 'self'"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert not [h for h in res.headers if h.startswith("access-control-")]


def test_static_files_need_no_identity_but_the_api_still_does(client: Client) -> None:
    assert client.get("/app.js").status == 200
    assert client.get("/api/posts").status == 200  # dev mode reads are open


@pytest.mark.parametrize(
    "path",
    [
        "/static/app.js",
        "/web/app.js",
        "/app.js/",
        "/../serve.py",
        "/%2e%2e/serve.py",
        "/..%2fserve.py",
        "/__init__.py",
        "/icons.svg/../index.html/",
        "/favicon.ico",
        "/apple.css",
        "/api",
    ],
)
def test_paths_outside_the_allow_list_are_404(client: Client, path: str) -> None:
    res = client.get(path)
    assert res.status == 404, path
    assert json.loads(res.raw)["error"]["code"] == "NOT_FOUND"


def test_a_query_string_does_not_change_the_page(client: Client) -> None:
    assert client.get("/?view=month&date=2026-03-09").raw == (WEB / "index.html").read_bytes()


def test_post_to_a_page_is_404(client: Client) -> None:
    assert client.call("POST", "/").status == 404


def test_index_has_no_inline_script_handlers_or_styles(client: Client) -> None:
    html = text("index.html")
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, flags=re.S | re.I)
    assert scripts
    for attrs, body in scripts:
        assert "src=" in attrs and not body.strip()
    assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I)
    assert not re.search(r"\sstyle\s*=", html, flags=re.I)
    assert "<style" not in html.lower()
    assert "javascript:" not in html.lower()


def test_theme_script_blocks_in_head_before_styles(client: Client) -> None:
    html = text("index.html")
    head = html[: html.index("</head>")]
    theme = re.search(r'<script\b[^>]*src="/theme\.js"[^>]*>', head)
    assert theme is not None
    assert "defer" not in theme.group(0) and "async" not in theme.group(0)
    assert theme.start() < head.index("/app.css")


def test_index_references_only_allow_listed_assets() -> None:
    html = text("index.html")
    for ref in re.findall(r'(?:src|href)="([^"#]+)', html):
        assert ref in ASSETS, ref


def test_assets_make_no_external_requests() -> None:
    for name in ("index.html", "app.css", "app.js", "theme.js", "icons.svg"):
        body = text(name).replace(NAMESPACE, "")
        assert not re.search(r"(?:https?:)?//[a-z0-9]", body, flags=re.I), name
        assert "@import" not in body and "url(" not in body, name


def test_the_sprite_has_every_status_type_and_a_fallback() -> None:
    ids = set(re.findall(r'<symbol[^>]*\bid="([^"]+)"', text("icons.svg")))
    schema = actions.schema()
    for state in schema["states"]:  # type: ignore[attr-defined]
        assert f"status-{state}" in ids
    for kind in actions.POST_TYPES:
        assert f"type-{kind}" in ids
    assert {"status-generic", "type-generic", "platform-generic"} <= ids
    assert 'stroke-width="1.5"' in text("icons.svg")
    assert not re.search(r'(?:fill|stroke)="#', text("icons.svg"))


def test_the_ui_never_uses_inner_html_or_transition_all() -> None:
    js = text("app.js") + text("theme.js")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", js)
    assert not re.search(r"transition:\s*all", text("app.css"))


def test_outside_month_days_keep_full_text_contrast() -> None:
    css = text("app.css")
    rule = re.search(r'\.day\[data-outside="true"\]\s*\{([^}]*)\}', css)
    assert rule and "opacity" not in rule.group(1)


def test_the_sticky_bar_does_not_hide_keyboard_focus() -> None:
    assert re.search(r"html\s*\{[^}]*scroll-padding-top:\s*\d+px", text("app.css"))


def test_the_bar_is_not_sticky_in_small_viewports_or_at_large_zoom() -> None:
    css = text("app.css")
    query = r"@media \(max-width: 760px\), \(max-height: 560px\)"
    block = re.search(query + r"\s*\{(.*?)\n\}", css, re.S)
    assert block
    assert re.search(r"\.bar\s*\{[^}]*position:\s*static", block.group(1))
    assert re.search(r"\.panel\s*\{[^}]*top:\s*12px\s*!important", block.group(1))


def rule(selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text("app.css"))
    assert match, selector
    return match.group(1)


def test_text_sizes_are_rem_based_with_no_px_font_sizes() -> None:
    css = text("app.css")
    assert not re.search(r"font-size:\s*[\d.]+px", css)
    assert re.search(r"html\s*\{[^}]*font-size:\s*87\.5%", css)
    assert re.search(r'html\s*\{[^}]*font-family:\s*"Inter",\s*system-ui', css)


def test_glass_is_a_24px_blur_with_a_72_percent_fill() -> None:
    assert rule(".glass").count("blur(24px)") == 2
    for selector in (":root", ':root[data-theme="dark"]'):
        assert re.search(r"--panel-glass:\s*rgba\([^)]*,\s*0\.72\)", rule(selector)), selector
    assert "backdrop-filter: none" in re.search(
        r"@media \(prefers-reduced-transparency: reduce\)\s*\{(.*?)\n\}", text("app.css"), re.S
    ).group(1)  # type: ignore[union-attr]


def test_the_entrance_is_subtle_and_reduced_motion_fades_only() -> None:
    css = text("app.css")
    keyframes = re.search(r"@keyframes rise\s*\{(.*?)\}\s*to", css, re.S)
    assert (
        keyframes and "translateY(4px)" in keyframes.group(1) and "blur(2px)" in keyframes.group(1)
    )
    assert "250ms" in rule(".enter .rise")
    fade = re.search(r"@keyframes rise-fade\s*\{(.*?)\}\s*\}", css, re.S)
    assert fade and "transform" not in fade.group(1) and "filter" not in fade.group(1)
    reduced = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}", css, re.S)
    assert reduced and "animation: rise-fade" in reduced.group(1)
    assert "animation: none" not in reduced.group(1)


def test_the_needs_strip_is_a_collapsible_button() -> None:
    html = text("index.html")
    button = re.search(r'<button\b[^>]*id="needs-toggle"[^>]*>', html)
    assert (
        button
        and 'aria-expanded="true"' in button.group(0)
        and 'aria-controls="needs"' in button.group(0)
    )
    assert 'id="needs"' in html and "localStorage" in text("app.js")


def test_the_panel_sits_beside_the_grid_from_1200px_and_over_a_scrim_below() -> None:
    css = text("app.css")
    assert re.search(
        r"@media \(min-width: 1200px\)\s*\{[^@]*main\s*\{\s*padding-right:\s*calc\(var\(--panel",
        css,
    )
    assert 'id="scrim"' in text("index.html")


def test_unexpected_errors_are_a_json_500_without_detail(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("secret-detail /home/someone/brand.db")

    monkeypatch.setattr(serve.actions, "ui_schema", boom)
    res = client.get("/api/schema?token=abc123")
    assert res.status == 500
    assert res.headers["content-type"] == "application/json"
    assert res.headers["content-security-policy"] == "default-src 'self'"
    body = json.loads(res.raw)
    assert body["ok"] is False and body["error"]["code"] == "INTERNAL"
    assert body["error"]["message"] and body["error"]["next"]
    assert res.headers["x-brandcal-exit"] == str(serve.EXIT_INTERNAL)
    dumped = res.raw.decode()
    for leak in ("Traceback", "secret-detail", "RuntimeError", "abc123", "brand.db", "File "):
        assert leak not in dumped
    monkeypatch.undo()
    assert client.get("/api/schema").status == 200  # the server carries on
