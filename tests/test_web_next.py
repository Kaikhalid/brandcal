"""The Next.js UI served at `/` by `brandcal serve`: routing, safe paths, types and per-page CSP.

The routing tests run against a small fake tree so they do not depend on a build; the last
tests check the committed build in ``src/brandcal/web_next/`` against its ``csp.json``.
"""

from __future__ import annotations

import base64
import hashlib
import html
import http.client
import json
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from ui_env import make_home

from brandcal import serve
from brandcal.config import load_config

BUILT = Path(serve.__file__).parent / "web_next"
DEFAULT_CSP = "default-src 'self'"
PAGE = b"<!doctype html><title>Example Co</title>"
CSP_FILE = {
    "index.html": {"script": ["sha256-AAA="], "style": ["sha256-BBB="], "style_attr": []},
    "x/index.html": {"script": ["sha256-XXX="], "style": [], "style_attr": ["sha256-SSS="]},
}


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    raw: bytes


def fetch(port: int, path: str, method: str = "GET") -> Resp:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path)
        res = conn.getresponse()
        return Resp(res.status, {k.lower(): v for k, v in res.getheaders()}, res.read())
    finally:
        conn.close()


def start(home: Path, root: Path) -> tuple[int, object]:
    server = serve.make_server(home, load_config(home), 0, None, dev=True, static_root=root)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1], server


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "web_next"
    for rel, data in {
        "index.html": PAGE,
        "x/index.html": PAGE + b"<!-- x -->",
        "plain/index.html": PAGE + b"<!-- not in the manifest -->",
        "_next/static/chunks/app.js": b"console.log(1)",
        "_next/static/css/app.css": b"body{margin:0}",
        "_next/static/media/f.woff2": b"wOF2",
        "index.txt": b"0:rsc",
        "logo.svg": b"<svg/>",
        "favicon.ico": b"\0\0\1\0",
        "icon.png": b"\x89PNG",
        "data.json": b"{}",
        "secret.map": b"{}",
        ".hidden.html": b"hidden",
        ".well/known.txt": b"hidden",
        "csp.json": json.dumps(CSP_FILE).encode(),
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    (root / "empty").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    (outside / "secret.js").write_text("outside", encoding="utf-8")
    try:
        (root / "link.js").symlink_to(outside / "secret.js")
        (root / "linkdir").symlink_to(outside, target_is_directory=True)
    except OSError:  # pragma: no cover - platforms without symlinks
        pytest.skip("symlinks are not available")
    return root


@pytest.fixture
def port(tmp_path: Path, tree: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    home = make_home(tmp_path / "home", monkeypatch)
    number, server = start(home, tree)
    yield number
    server.shutdown()  # type: ignore[attr-defined]
    server.server_close()  # type: ignore[attr-defined]


def test_slash_serves_the_new_ui_index(port: int) -> None:
    res = fetch(port, "/")
    assert res.status == 200 and res.raw == PAGE
    assert res.headers["content-type"] == "text/html; charset=utf-8"
    for path in ("/index.html", "/?post=launch-thread", "/?a=1&b=%2e%2e"):
        assert fetch(port, path).raw == PAGE, path


def test_a_folder_route_serves_its_index_and_the_bare_name_redirects(port: int) -> None:
    assert fetch(port, "/x/").raw == PAGE + b"<!-- x -->"
    res = fetch(port, "/x")
    assert res.status == 308 and res.headers["location"] == "/x/"
    assert res.raw == b""
    assert fetch(port, "/x?post=a").headers["location"] == "/x/?post=a"
    assert fetch(port, "/x/index.html").status == 200


@pytest.mark.parametrize("path", ["/nope", "/nope/", "/empty", "/empty/", "/x/nope", "/index"])
def test_unknown_routes_are_the_json_404_and_never_redirect(port: int, path: str) -> None:
    res = fetch(port, path)
    assert res.status == 404, path
    assert res.headers["content-type"] == "application/json"
    assert json.loads(res.raw)["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("path", "ctype"),
    [
        ("/index.html", "text/html; charset=utf-8"),
        ("/_next/static/chunks/app.js", "text/javascript; charset=utf-8"),
        ("/_next/static/css/app.css", "text/css; charset=utf-8"),
        ("/_next/static/media/f.woff2", "font/woff2"),
        ("/index.txt", "text/x-component"),
        ("/logo.svg", "image/svg+xml"),
        ("/favicon.ico", "image/x-icon"),
        ("/icon.png", "image/png"),
        ("/data.json", "application/json"),
    ],
)
def test_files_get_an_explicit_content_type_and_the_hardening_headers(
    port: int, path: str, ctype: str
) -> None:
    res = fetch(port, path)
    assert res.status == 200, path
    assert res.headers["content-type"] == ctype
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["cache-control"] == "no-store"
    assert not [h for h in res.headers if h.startswith("access-control-")]


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.txt",
        "/x/../../secret.txt",
        "/%2e%2e/secret.txt",
        "/%2E%2E/secret.txt",
        "/..%2fsecret.txt",
        "/x/..%2F..%2Fsecret.txt",
        "/x/%2e%2e/%2e%2e/secret.txt",
        "/_next/static/..%2f..%2fcsp.json",
        "/_next/static/%252e%252e/csp.json",
        "/..\\secret.txt",
        "/x\\..\\secret.txt",
        "/_next/..%5csecret.txt",
        "/%5c..%5csecret.txt",
        "/%00",
        "/index.html%00.png",
        "/%00/index.html",
        "/.hidden.html",
        "/%2ehidden.html",
        "/.well/known.txt",
        "/x/./index.html",
        "/./index.html",
        "/x//index.html",  # (a leading "//" is collapsed to "/" by http.server itself)
        "/link.js",
        "/linkdir/secret.txt",
        "/linkdir/",
        "/csp.json",
        "/secret.map",
        "/index.html/",
        "/%0d%0aSet-Cookie:a=b",
    ],
)
def test_unsafe_paths_are_refused(port: int, path: str) -> None:
    res = fetch(port, path)
    assert res.status == 404, path
    assert json.loads(res.raw)["error"]["code"] == "NOT_FOUND"
    assert b"outside" not in res.raw and b"hidden" not in res.raw


def test_a_page_in_the_manifest_gets_its_own_hashes_and_nothing_unsafe(port: int) -> None:
    index = fetch(port, "/").headers["content-security-policy"]
    assert index == (
        "default-src 'self'; script-src 'self' 'sha256-AAA='; style-src 'self' 'sha256-BBB='"
    )
    x = fetch(port, "/x/").headers["content-security-policy"]
    assert x == (
        "default-src 'self'; script-src 'self' 'sha256-XXX=';"
        " style-src 'self' 'unsafe-hashes' 'sha256-SSS='"
    )
    for policy in (index, x):
        assert "'unsafe-inline'" not in policy and "'unsafe-eval'" not in policy


def test_hashes_of_one_page_are_not_sent_with_another(port: int) -> None:
    assert "sha256-XXX=" not in fetch(port, "/").headers["content-security-policy"]
    assert "sha256-AAA=" not in fetch(port, "/x/").headers["content-security-policy"]


def test_unhashed_pages_and_all_other_responses_keep_the_plain_policy(port: int) -> None:
    for path in (
        "/plain/",
        "/_next/static/chunks/app.js",
        "/index.txt",
        "/api/session",
        "/nope",
        "/mvp/",
        "/x",
    ):
        policy = fetch(port, path).headers["content-security-policy"]
        assert policy == DEFAULT_CSP, path


def test_the_manifest_is_read_once_at_start(port: int, tree: Path) -> None:
    before = fetch(port, "/").headers["content-security-policy"]
    (tree / "csp.json").write_text("{}", encoding="utf-8")
    assert fetch(port, "/").headers["content-security-policy"] == before


def test_without_a_manifest_pages_get_the_plain_policy(
    tmp_path: Path, tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tree / "csp.json").unlink()
    number, server = start(make_home(tmp_path / "home", monkeypatch), tree)
    try:
        res = fetch(number, "/")
        assert res.status == 200 and res.headers["content-security-policy"] == DEFAULT_CSP
    finally:
        server.shutdown()  # type: ignore[attr-defined]
        server.server_close()  # type: ignore[attr-defined]


def test_api_routes_are_unchanged(port: int) -> None:
    res = fetch(port, "/api/session")
    assert res.status == 200 and json.loads(res.raw)["ok"] is True
    assert fetch(port, "/api/nope").status == 404


# -- the committed build ---------------------------------------------------------------------


def sha(data: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(data.encode()).digest()).decode()


def inline_hashes(page: str) -> dict[str, list[str]]:
    """Hashes of inline script and style bodies and style="" values, as a browser sees them."""
    scripts = [
        body
        for attrs, body in re.findall(r"<script\b([^>]*)>(.*?)</script>", page, re.S | re.I)
        if not re.search(r"\bsrc\s*=", attrs)
    ]
    styles = re.findall(r"<style\b[^>]*>(.*?)</style>", page, re.S | re.I)
    rest = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", page, flags=re.S | re.I)
    attrs = [html.unescape(v) for v in re.findall(r'\sstyle="([^"]*)"', rest)]
    unique = lambda items: sorted({sha(i) for i in items})  # noqa: E731
    return {"script": unique(scripts), "style": unique(styles), "style_attr": unique(attrs)}


def built_pages() -> list[Path]:
    return sorted(BUILT.rglob("*.html"))


def test_the_build_is_committed() -> None:
    assert (BUILT / "index.html").is_file() and (BUILT / "csp.json").is_file()


def test_csp_json_matches_the_inline_code_of_every_built_page() -> None:
    manifest = json.loads((BUILT / "csp.json").read_text(encoding="utf-8"))
    pages = {p.relative_to(BUILT).as_posix() for p in built_pages()}
    assert set(manifest) == pages
    for rel in pages:
        page = (BUILT / rel).read_text(encoding="utf-8")
        assert manifest[rel] == inline_hashes(page), rel


def test_the_built_home_page_is_served_with_its_own_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    number, server = start(make_home(tmp_path / "home", monkeypatch), BUILT)
    try:
        res = fetch(number, "/")
        assert res.status == 200 and res.raw == (BUILT / "index.html").read_bytes()
        policy = res.headers["content-security-policy"]
        manifest = json.loads((BUILT / "csp.json").read_text(encoding="utf-8"))["index.html"]
        assert policy.startswith("default-src 'self'; script-src 'self' ")
        for digest in manifest["script"]:
            assert f"'{digest}'" in policy
        assert "'unsafe-inline'" not in policy and "'unsafe-eval'" not in policy
        favicon = 200 if (BUILT / "favicon.ico").exists() else 404
        assert fetch(number, "/favicon.ico").status == favicon
    finally:
        server.shutdown()
        server.server_close()


def test_built_pages_have_no_inline_event_handlers_or_external_urls() -> None:
    for page in built_pages():
        body = page.read_text(encoding="utf-8")
        markup = re.sub(r"<script.*?</script>", "", body, flags=re.S)
        assert not re.search(r"\son[a-z]+\s*=", markup), page
        assert not re.search(r'(?:src|href)="https?://', body), page
