"""The connector (spec 5, 6, 8): backoff, liveness, replay rules, caps and the log."""

from __future__ import annotations

import io
import queue
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from ws_env import ACCESS, HOST, SECRET, TZ, FakeDO, Running, Upstream, free_port, wait_until

from brandcal import relay

FAST = relay.Timing(
    connect=0.5, response=1.0, handshake=2.0, ping=0.05, text_ping=0.1, stale=1.0, tick=0.02
)
JWT = "e30.JWT-VALUE-NOT-REAL.sig"
EMAIL = "someone@example.com"
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+03:00")


@dataclass
class Rig:
    do: FakeDO
    up: Upstream
    log: io.StringIO
    connector: relay.Connector
    running: Running | None = None

    def lines(self) -> list[str]:
        return self.log.getvalue().splitlines()

    def close(self) -> None:
        if self.running is not None:
            self.running.stop()
        self.do.close()
        self.up.close()


@pytest.fixture
def rig() -> Iterator[Callable[..., Rig]]:
    made: list[Rig] = []

    def make(
        *,
        server: dict[str, Any] | None = None,
        timing: relay.Timing = FAST,
        max_response: int = 32 * 1024 * 1024,
        up_port: int | None = None,
        start: bool = True,
        log: io.StringIO | None = None,
        **kw: Any,
    ) -> Rig:
        do, up, log = FakeDO(**(server or {})), Upstream(), log or io.StringIO()
        settings = relay.Settings(do.url, HOST, up_port or up.port, SECRET, ACCESS, max_response)
        connector = relay.Connector(settings, TZ, timing=timing, out=log, **kw)
        made.append(Rig(do, up, log, connector))
        if start:
            made[-1].running = Running(connector)
            do.wait_ready()
        return made[-1]

    yield make
    for item in made:
        item.close()


def hdrs(*extra: tuple[str, str]) -> list[tuple[str, str]]:
    return [("Host", HOST), *extra]


# -- backoff and reconnecting ---------------------------------------------------------------------


def test_backoff_doubles_from_one_second_to_sixty_with_full_jitter() -> None:
    top = relay.Backoff(lambda: 1.0)
    assert [top.next(0) for _ in range(9)] == [1, 2, 4, 8, 16, 32, 60, 60, 60]
    half = relay.Backoff(lambda: 0.5)
    assert [half.next(0) for _ in range(4)] == [0.5, 1, 2, 4]
    assert relay.Backoff(lambda: 0.0).next(0) == 0.0


def test_backoff_resets_only_after_five_minutes_connected() -> None:
    b = relay.Backoff(lambda: 1.0)
    assert [b.next(0), b.next(299.9), b.next(10)] == [1, 2, 4]
    assert [b.next(300), b.next(0)] == [1, 2]


def test_failed_connections_back_off_with_the_injected_random_and_sleep(
    rig: Callable[..., Rig],
) -> None:
    delays: list[float] = []
    holder: list[relay.Connector] = []

    def sleep(seconds: float) -> None:
        delays.append(seconds)
        if len(delays) == 5:
            holder[0].stop()

    r = rig(start=False, rand=lambda: 0.5, sleep=sleep)
    holder.append(r.connector)
    r.do.close()  # nothing is listening any more: every attempt is refused
    assert r.connector.run() == {"ok": True, "stopped": True}
    assert delays == [0.5, 1.0, 2.0, 4.0, 8.0]
    assert any("disconnect error=ConnectionRefusedError backoff=1.00s" in x for x in r.lines())


def test_a_long_connection_resets_the_backoff(rig: Callable[..., Rig]) -> None:
    skew = [0.0]
    delays: list[float] = []
    holder: list[relay.Connector] = []

    class Log(io.StringIO):
        def write(self, text: str) -> int:
            if "connected ready" in text:
                skew[0] += 400  # six and a half minutes pass while the session is up
            return super().write(text)

    def sleep(seconds: float) -> None:
        delays.append(seconds)
        if len(delays) == 3:
            holder[0].stop()

    r = rig(
        start=False, server={"close_after_ready": 1012}, rand=lambda: 1.0, sleep=sleep,
        clock=lambda: time.monotonic() + skew[0], log=Log(),
    )  # fmt: skip
    holder.append(r.connector)
    r.connector.run()
    assert delays == [1.0, 1.0, 1.0]  # never 1, 2, 4: each session counted as long
    assert any("disconnect close=1012 backoff=1.00s" in x for x in r.lines())


def test_other_closes_and_other_http_statuses_reconnect(rig: Callable[..., Rig]) -> None:
    closing = rig(server={"close_after_ready": 1012}, sleep=lambda s: time.sleep(0.01), start=False)
    closing.running = Running(closing.connector)
    wait_until(lambda: closing.do.connections >= 3)
    unavailable = rig(server={"refuse": 530}, sleep=lambda s: time.sleep(0.01), start=False)
    unavailable.running = Running(unavailable.connector)
    wait_until(lambda: len(unavailable.do.server.requests) >= 3)
    assert any("disconnect status=530" in x for x in unavailable.lines())


# -- liveness -------------------------------------------------------------------------------------


def test_pings_keep_the_connection_up(rig: Callable[..., Rig]) -> None:
    r = rig(timing=relay.Timing(ping=0.05, text_ping=0.1, stale=0.3, tick=0.02))
    wait_until(lambda: r.do.pings >= 3 and r.do.texts >= 2)
    time.sleep(0.4)  # longer than the stale limit: pongs keep it alive
    assert r.do.connections == 1


def test_no_frame_for_the_stale_limit_reconnects(rig: Callable[..., Rig]) -> None:
    r = rig(
        server={"answer": False},
        timing=relay.Timing(ping=0.05, text_ping=0.1, stale=0.2, tick=0.02),
        sleep=lambda s: time.sleep(0.01),
    )
    wait_until(lambda: r.do.connections >= 2)
    assert any("error=Stale" in x for x in r.lines())


# -- replay rules ---------------------------------------------------------------------------------


def test_a_get_is_replayed_and_the_answer_streamed_back(rig: Callable[..., Rig]) -> None:
    r = rig()
    r.up.body = b"x" * 600_000
    reply = r.do.fetch("GET", "/api/posts?status=idea", hdrs())
    assert reply.status == 200 and reply.body == r.up.body
    assert reply.kinds.count(relay.RES_BODY) == 3  # 256 KiB chunks at most
    assert reply.kinds[0] == relay.RES_HEAD and reply.kinds[-1] == relay.RES_END
    assert (r.up.seen[0]["method"], r.up.seen[0]["path"]) == ("GET", "/api/posts?status=idea")


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("Host", "evil.example.com")],
        [("Host", HOST.upper())],
        [("Host", HOST + ".evil.example.com")],
        [("Host", HOST), ("Host", HOST)],
        [("Host", HOST), ("host", "evil.example.com")],
        [("Host", "127.0.0.1:8787")],
    ],
)
def test_host_must_equal_the_public_host_exactly(
    rig: Callable[..., Rig], headers: list[tuple[str, str]]
) -> None:
    r = rig()
    assert r.do.fetch("GET", "/api/session", headers).error == "BAD_FRAME"
    assert r.up.seen == []


@pytest.mark.parametrize(
    "path",
    [
        "/a\rb",
        "/a\nb",
        "/a\x00b",
        "/a b",
        "/a\tb",
        "api/x",
        "",
        "http://x/",
        "/caf\u00e9",
        "/a\x7fb",
    ],
)
def test_bad_paths_never_reach_brandcal(rig: Callable[..., Rig], path: str) -> None:
    r = rig()
    assert r.do.fetch("GET", path, hdrs()).error == "BAD_FRAME"
    assert r.up.seen == []
    wait_until(lambda: "stream=1 " in r.log.getvalue())
    assert not any("\r" in x or "\x00" in x for x in r.lines())
    assert "path=- " in r.log.getvalue()  # a refused path is not logged


@pytest.mark.parametrize("method", ["PUT", "DELETE", "OPTIONS", "get", "GET\r\nX: y", "HEAD"])
def test_only_get_and_post_are_replayed(rig: Callable[..., Rig], method: str) -> None:
    r = rig()
    assert r.do.fetch(method, "/api/session", hdrs()).error == "BAD_FRAME"
    assert r.up.seen == []


def test_header_values_with_line_breaks_are_refused(rig: Callable[..., Rig]) -> None:
    r = rig()
    bad = hdrs(("Origin", "https://brandcal.example.com\r\nX-Evil: 1"))
    assert r.do.fetch("GET", "/api/session", bad).error == "BAD_FRAME"
    assert r.up.seen == []


def test_a_malformed_req_payload_is_bad_frame(rig: Callable[..., Rig]) -> None:
    r = rig()
    assert r.do.peer is not None
    r.do.streams[40] = queue.Queue()
    r.do.peer.send(2, relay.encode(relay.REQ, 40, b"garbage"))
    assert r.do.collect(40).error == "BAD_FRAME"


def test_request_headers_are_re_emitted_from_the_allow_list_only(rig: Callable[..., Rig]) -> None:
    r = rig()
    sent = hdrs(
        ("Cf-Access-Jwt-Assertion", JWT),
        ("Origin", f"https://{HOST}"),
        ("Content-Type", "application/json"),
        ("Accept", "application/json"),
        ("X-Brandcal-CSRF", "csrf-value"),
        ("Content-Length", "999"),  # never trusted: recomputed
        ("Cookie", "CF_Authorization=cookie-value"),
        ("Authorization", "Bearer nope"),
        ("Cf-Access-Authenticated-User-Email", EMAIL),
        ("Cf-Connecting-IP", "203.0.113.9"),
        ("X-Forwarded-For", "203.0.113.9"),
        ("Forwarded", "for=203.0.113.9"),
        ("Connection", "keep-alive"),
        ("Transfer-Encoding", "chunked"),
        ("Upgrade", "websocket"),
        ("Proxy-Authorization", "x"),
        ("TE", "trailers"),
        ("Accept-Encoding", "gzip"),
        ("User-Agent", "Mozilla"),
    )
    body = b'{"version":3}'
    assert r.do.fetch("POST", "/api/posts/p0001/approve", sent, body).status == 200
    seen = r.up.seen[0]
    assert r.up.header_names() == {
        "host", "cf-access-jwt-assertion", "origin", "content-type", "accept",
        "x-brandcal-csrf", "content-length",
    }  # fmt: skip
    got = {k.lower(): v for k, v in seen["headers"]}
    assert got["host"] == HOST and got["cf-access-jwt-assertion"] == JWT
    assert got["content-length"] == str(len(body)) and seen["body"] == body


def test_a_get_without_a_body_sends_no_content_length(rig: Callable[..., Rig]) -> None:
    r = rig()
    assert r.do.fetch("GET", "/", hdrs(("Content-Length", "5"))).status == 200
    assert r.up.header_names() == {"host"}


def test_response_headers_are_re_emitted_from_the_allow_list_only(rig: Callable[..., Rig]) -> None:
    r = rig()
    r.up.status = 308
    r.up.body = b""
    r.up.headers = [
        ("Content-Type", "text/plain"), ("Cache-Control", "no-store"), ("Location", "/mvp/"),
        ("Content-Security-Policy", "default-src 'self'"), ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"), ("Allow", "GET, POST"), ("X-Brandcal-Exit", "0"),
        ("Set-Cookie", "a=b"), ("X-Powered-By", "x"), ("Access-Control-Allow-Origin", "*"),
        ("Server-Timing", "x"), ("Connection", "close"),
    ]  # fmt: skip
    reply = r.do.fetch("GET", "/mvp", hdrs())
    assert reply.status == 308  # statuses pass through unchanged
    assert {k.lower() for k, _ in reply.headers} == {
        "content-type", "cache-control", "location", "content-security-policy",
        "x-content-type-options", "referrer-policy", "allow", "x-brandcal-exit", "content-length",
    }  # fmt: skip
    assert dict(map(tuple, reply.headers))["Location"] == "/mvp/"  # type: ignore[arg-type]


# -- caps and upstream failures -------------------------------------------------------------------


def test_the_response_cap_with_a_declared_length_fails_before_the_head(
    rig: Callable[..., Rig],
) -> None:
    r = rig(max_response=1000)
    r.up.body = b"y" * 1001
    reply = r.do.fetch("GET", "/big", hdrs())
    assert reply.error == "TOO_LARGE" and reply.kinds == [relay.RES_ERR]
    r.up.body = b"y" * 1000
    assert r.do.fetch("GET", "/exact", hdrs()).status == 200


def test_the_response_cap_without_a_length_aborts_after_the_head(rig: Callable[..., Rig]) -> None:
    r = rig(max_response=1000)
    r.up.body, r.up.close_delimited = b"y" * 5000, True
    reply = r.do.fetch("GET", "/big", hdrs())
    assert reply.error == "TOO_LARGE" and reply.kinds[0] == relay.RES_HEAD
    assert reply.kinds[-1] == relay.RES_ERR and len(reply.body) <= 1000


def test_brandcal_not_running_is_upstream_down(rig: Callable[..., Rig]) -> None:
    r = rig(up_port=free_port())
    reply = r.do.fetch("GET", "/api/session", hdrs())
    assert reply.error == "UPSTREAM_DOWN" and reply.kinds == [relay.RES_ERR]
    assert "outcome=UPSTREAM_DOWN" in r.log.getvalue()


def test_a_slow_brandcal_is_upstream_timeout(rig: Callable[..., Rig]) -> None:
    r = rig(timing=relay.Timing(connect=0.5, response=0.2, ping=0.05, tick=0.02))
    r.up.stall = threading.Event()
    began = time.monotonic()
    assert r.do.fetch("GET", "/slow", hdrs()).error == "UPSTREAM_TIMEOUT"
    assert time.monotonic() - began < 2


def test_the_whole_response_has_one_deadline(rig: Callable[..., Rig]) -> None:
    r = rig(timing=relay.Timing(connect=0.5, response=0.3, ping=0.05, tick=0.02))
    r.up.stall = threading.Event()  # the head never comes
    reply = r.do.fetch("GET", "/slow", hdrs())
    assert reply.error == "UPSTREAM_TIMEOUT" and reply.status is None


def test_cancel_drops_the_upstream_connection_and_sends_nothing_more(
    rig: Callable[..., Rig],
) -> None:
    r = rig()
    r.up.stall = threading.Event()
    stream = r.do.send_req("GET", "/slow", hdrs())
    wait_until(lambda: r.up.seen)
    r.do.cancel(stream)
    wait_until(lambda: "outcome=cancelled" in r.log.getvalue())
    r.up.stall.set()
    time.sleep(0.05)
    assert r.do.streams[stream].empty()


def test_requests_run_in_parallel(rig: Callable[..., Rig]) -> None:
    r = rig()
    r.up.stall = threading.Event()
    streams = [r.do.send_req("GET", f"/p{i}", hdrs()) for i in range(6)]
    wait_until(lambda: len(r.up.seen) == 6)  # all six in flight at once, on the pool of 8
    r.up.stall.set()
    assert [r.do.collect(s).status for s in streams] == [200] * 6


# -- the log --------------------------------------------------------------------------------------


def test_request_lines_have_the_configured_offset_and_no_query(rig: Callable[..., Rig]) -> None:
    fixed = datetime(2026, 10, 24, 6, 15, 2, tzinfo=UTC)
    r = rig(now=lambda: fixed)
    r.do.fetch("GET", "/api/session?csrf=1&x=y", hdrs())
    wait_until(lambda: any("stream=1 " in x for x in r.lines()))
    line = next(x for x in r.lines() if "stream=1 " in x)
    assert re.fullmatch(
        r"2026-10-24T09:15:02\+03:00 stream=1 method=GET path=/api/session status=200"
        r" ms=\d+ bytes=5 outcome=ok",
        line,
    )


def test_every_line_has_a_plus_three_stamp_and_never_z_or_utc(rig: Callable[..., Rig]) -> None:
    r = rig()  # the real clock, converted to the configured display zone
    r.do.fetch("GET", "/api/session", hdrs())
    r.do.fetch("GET", "no-slash", hdrs())
    wait_until(lambda: len(r.lines()) >= 3)
    for line in r.lines():
        assert STAMP.match(line), line
        assert "+00:00" not in line and not re.match(r"\S*Z\s", line)


def test_close_codes_and_backoff_are_logged(rig: Callable[..., Rig]) -> None:
    r = rig(
        server={"close_after_ready": 4999}, start=False,
        sleep=lambda s: time.sleep(0.01), rand=lambda: 0.5,
    )  # fmt: skip
    r.running = Running(r.connector)
    wait_until(lambda: any("disconnect close=4999 backoff=0.50s" in x for x in r.lines()))


def test_the_log_never_holds_headers_bodies_tokens_or_secrets(rig: Callable[..., Rig]) -> None:
    r = rig()
    sent = hdrs(
        ("Cf-Access-Jwt-Assertion", JWT),
        ("Cookie", "CF_Authorization=cookie-value"),
        ("Cf-Access-Authenticated-User-Email", EMAIL),
        ("X-Brandcal-CSRF", "csrf-value-not-real"),
        ("Cf-Connecting-IP", "203.0.113.9"),
        ("Content-Type", "application/json"),
    )
    r.do.fetch("POST", "/api/posts/p1/approve?token=" + JWT, sent, b"BODY-TEXT-NOT-LOGGED")
    wait_until(lambda: any("stream=1 " in x for x in r.lines()))
    text = r.log.getvalue()
    for secret in (
        JWT, "cookie-value", EMAIL, "csrf-value-not-real", "203.0.113.9", "BODY-TEXT-NOT-LOGGED",
        SECRET.decode(), ACCESS[0], ACCESS[1], "CF-Access-Client", "hello",
    ):  # fmt: skip
        assert secret not in text, secret
    assert "path=/api/posts/p1/approve " in text
