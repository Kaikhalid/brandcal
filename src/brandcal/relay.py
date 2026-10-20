"""`brandcal relay`: the connector for the Cloudflare Worker relay (docs/RELAY_CONNECTOR.md).

The box cannot reach a tunnel edge, so it dials out instead: one WebSocket over 443 to the
Worker's Durable Object. The Durable Object sends each browser request down that socket; the
connector replays it against ``http://127.0.0.1:<serve.port>`` and streams the answer back.
This module holds the frame format (protocol v1), the settings, and the connector; the
WebSocket itself is ``wsclient``. Only allow-listed headers cross in either direction, and the
log never holds a header value, body, token, secret, email or client address.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import http.client
import json
import random
import re
import signal
import socket
import struct
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any, NamedTuple, TextIO
from urllib.parse import urlsplit

from brandcal import __version__, timefmt, wsclient
from brandcal.config import display_tz
from brandcal.errors import BrandcalError, ErrorCode

# -- frames (spec 5): type:u8 | stream:u32be | payload ------------------------------------------

HELLO, CHALLENGE, PROOF, READY = 0x00, 0x01, 0x02, 0x03
REQ, CANCEL = 0x10, 0x11
RES_HEAD, RES_BODY, RES_END, RES_ERR = 0x20, 0x21, 0x22, 0x23
CONNECTION_FRAMES = (HELLO, CHALLENGE, PROOF, READY)  # always stream 0
STREAM_FRAMES = (REQ, CANCEL, RES_HEAD, RES_BODY, RES_END, RES_ERR)  # never stream 0
MAX_FRAME = 1024 * 1024
CHUNK = 256 * 1024
PROTOCOL = b"brandcal-relay.v1"
HEAD = struct.Struct(">BI")


class FrameError(ValueError):
    """A frame breaks the v1 format."""


class Frame(NamedTuple):
    kind: int
    stream: int
    payload: bytes


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    headers: list[tuple[str, str]]
    body: bytes


def encode(kind: int, stream: int, payload: bytes = b"") -> bytes:
    data = HEAD.pack(kind, stream) + payload
    if len(data) > MAX_FRAME:
        raise FrameError("a frame is over 1 MiB")
    return data


def decode(data: bytes) -> Frame:
    if len(data) < HEAD.size:
        raise FrameError("a frame is shorter than its 5-byte head")
    if len(data) > MAX_FRAME:
        raise FrameError("a frame is over 1 MiB")
    kind, stream = HEAD.unpack_from(data)
    payload = data[HEAD.size :]
    if kind in CONNECTION_FRAMES and stream != 0:
        raise FrameError("a connection frame has a stream id")
    if kind in STREAM_FRAMES and stream == 0:
        raise FrameError("a stream frame has stream id 0")
    if kind not in CONNECTION_FRAMES + STREAM_FRAMES:
        raise FrameError(f"unknown frame type {kind:#04x}")
    if kind in (CHALLENGE, PROOF) and len(payload) != 32:
        raise FrameError("a nonce or proof is not 32 bytes")
    if kind in (CANCEL, RES_END) and payload:
        raise FrameError("this frame type carries no payload")
    return Frame(kind, stream, payload)


def decode_json(payload: bytes) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except ValueError:
        raise FrameError("the payload is not UTF-8 JSON") from None
    if not isinstance(data, dict):
        raise FrameError("the payload is not a JSON object")
    return data


def _json(data: Mapping[str, object]) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode()


def encode_req(
    stream: int, method: str, path: str, headers: Sequence[tuple[str, str]], body: bytes = b""
) -> bytes:
    meta = _json({"m": method, "p": path, "h": [list(h) for h in headers], "bl": len(body)})
    return encode(REQ, stream, struct.pack(">I", len(meta)) + meta + body)


def decode_req(payload: bytes) -> Request:
    if len(payload) < 4:
        raise FrameError("a request has no JSON length")
    (size,) = struct.unpack_from(">I", payload)
    if size > len(payload) - 4:
        raise FrameError("the request JSON runs past the frame")
    meta, body = decode_json(payload[4 : 4 + size]), payload[4 + size :]
    method, path, pairs, length = (meta.get(k) for k in ("m", "p", "h", "bl"))
    if not (isinstance(method, str) and isinstance(path, str) and isinstance(pairs, list)):
        raise FrameError("a request needs m, p and h")
    headers: list[tuple[str, str]] = []
    for pair in pairs:
        ok = isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) for x in pair)
        if not ok:
            raise FrameError("a header is not a [name, value] pair")
        headers.append((pair[0], pair[1]))
    if length != len(body) or isinstance(length, bool):
        raise FrameError("bl does not match the body length")
    return Request(method, path, headers, body)


def encode_res_head(
    stream: int, status: int, headers: Sequence[tuple[str, str]], length: int | None
) -> bytes:
    return encode(
        RES_HEAD, stream, _json({"s": status, "h": [list(h) for h in headers], "bl": length})
    )


def proof(secret: bytes, nonce: bytes) -> bytes:
    """HMAC-SHA256(secret, nonce || "brandcal-relay.v1"): the secret itself never crosses."""
    return hmac.new(secret, nonce + PROTOCOL, hashlib.sha256).digest()


# -- settings (spec 8) ---------------------------------------------------------------------------

REQUEST_HEADERS = frozenset(
    ("cf-access-jwt-assertion", "origin", "content-type", "accept", "x-brandcal-csrf")
)  # plus Host, which is checked and then written from the settings
RESPONSE_HEADERS = frozenset(
    (
        "content-type",
        "content-length",
        "content-security-policy",
        "x-content-type-options",
        "referrer-policy",
        "cache-control",
        "location",
        "allow",
        "x-brandcal-exit",
    )
)
UPSTREAM_HOST = "127.0.0.1"  # fixed: it cannot be configured
DEFAULT_MAX_MB = 32
POOL = 8
_BAD_PATH = re.compile(r"[\x00-\x20\x7f]")
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_BAD_VALUE = re.compile(r"[\r\n\x00]")
DOC = "docs/RELAY_CONNECTOR.md"


@dataclass(frozen=True)
class Settings:
    url: str
    public_host: str
    port: int  # serve.port on 127.0.0.1
    secret: bytes = field(repr=False)
    access: tuple[str, str] | None = field(repr=False)  # (client_id, client_secret)
    max_response: int = DEFAULT_MAX_MB * 1024 * 1024  # bytes


def _bad(message: str) -> BrandcalError:
    return BrandcalError(ErrorCode.BAD_ARGS, message, f"Fix the relay block; see {DOC}.")


def _unavailable(what: str, path: str, why: str) -> BrandcalError:
    return BrandcalError(
        ErrorCode.SECRET_UNAVAILABLE,
        f"The {what} file {path} {why}.",
        "Check that the secret store is mounted and the path in relay is right.",
    )


def _text(block: Mapping[str, Any], key: str) -> str:
    value = block.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _bad(f"relay.{key} is required and must be text.")
    return value


def _read(path: str, what: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError:  # the OS message is dropped on purpose: the path is all the operator needs
        raise _unavailable(what, path, "is missing or cannot be read") from None


def _access_token(path: str, optional: bool) -> tuple[str, str] | None:
    if optional and not Path(path).exists():
        return None
    raw = _read(path, "access token")
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    named = isinstance(data, dict)
    client_id, client_secret = (
        (data.get("client_id"), data.get("client_secret")) if named else ("", "")
    )
    if (
        isinstance(client_id, str)
        and isinstance(client_secret, str)
        and client_id
        and client_secret
        and not _BAD_VALUE.search(client_id + client_secret)
    ):
        return client_id, client_secret
    raise _unavailable(
        "access token", path, 'must be JSON like {"client_id": "...", "client_secret": "..."}'
    )


def load_settings(cfg: Mapping[str, Any], local_dev: bool = False) -> Settings:
    """Validate the ``relay`` block and read both secret files, once. They stay in memory only."""
    block = cfg.get("relay")
    if not isinstance(block, dict):
        raise _bad("config.json has no relay block.")
    serve_block = cfg.get("serve")
    serve: dict[str, Any] = serve_block if isinstance(serve_block, dict) else {}
    url = _text(block, "url")
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        raise _bad("relay.url is not a valid URL.") from None
    local = local_dev and u.scheme == "ws" and u.hostname == "127.0.0.1" and port is not None
    if not ((u.scheme == "wss" and u.hostname) or local) or u.username or u.password:
        raise _bad("relay.url must be wss://HOST/PATH (ws://127.0.0.1:PORT only with --local-dev).")
    public_host = _text(block, "public_host")
    origins = serve.get("allowed_origins")
    hosts = (
        {urlsplit(o).netloc for o in origins if isinstance(o, str)}
        if isinstance(origins, list)
        else set()
    )
    if public_host not in hosts:
        raise _bad("relay.public_host must be the host of one of serve.allowed_origins.")
    serve_port = serve.get("port")
    if (
        not isinstance(serve_port, int)
        or isinstance(serve_port, bool)
        or not 0 < serve_port < 65536
    ):
        raise _bad("serve.port must be set (1 to 65535); the connector replays requests to it.")
    megabytes = block.get("max_response_mb", DEFAULT_MAX_MB)
    if not isinstance(megabytes, int | float) or isinstance(megabytes, bool):
        raise _bad("relay.max_response_mb must be a number.")
    if not 0 < megabytes <= 1024:
        raise _bad("relay.max_response_mb must be above 0 and at most 1024.")
    secret_path = _text(block, "secret_file")
    token_path = block.get("access_token_file")
    if token_path is None and not local:
        raise _bad("relay.access_token_file is required (only --local-dev may leave it out).")
    if token_path is not None and (not isinstance(token_path, str) or not token_path.strip()):
        raise _bad("relay.access_token_file must be a path.")
    secret = _read(secret_path, "relay secret").strip()
    if not secret:
        raise _unavailable("relay secret", secret_path, "is empty")
    access = None if token_path is None else _access_token(token_path, optional=local)
    return Settings(url, public_host, serve_port, secret, access, int(megabytes * 1024 * 1024))


# -- connector -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Timing:
    """Seconds; the defaults are the spec's. Tests pass short ones."""

    connect: float = 2.0  # to brandcal serve
    response: float = 25.0  # the whole answer from brandcal serve
    handshake: float = 10.0  # upgrade, challenge and ready
    ping: float = 20.0  # protocol ping
    text_ping: float = 60.0  # the text "ping" the Durable Object answers while hibernating
    stale: float = 45.0  # reconnect if no frame at all for this long
    tick: float = 0.25  # how often the read loop wakes to check the timers and the stop flag


DEFAULT_TIMING = Timing()


class Backoff:
    """Exponential backoff with full jitter: 1 s doubling to 60 s, reset after 5 minutes up."""

    def __init__(
        self, rand: Callable[[], float], base: float = 1.0, cap: float = 60.0, reset: float = 300.0
    ) -> None:
        self.rand, self.base, self.cap, self.reset, self.attempt = rand, base, cap, reset, 0

    def next(self, connected_for: float) -> float:
        if connected_for >= self.reset:
            self.attempt = 0
        ceiling = min(self.cap, self.base * 2**self.attempt)
        self.attempt += 1
        return float(self.rand() * ceiling)


class _Refuse(Exception):
    """Answer the stream with RES_ERR and this code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Cancelled(Exception):
    """The stream is over (CANCEL, or the socket went): send nothing more."""


class Stale(Exception):
    """No frame at all arrived within ``Timing.stale``."""


class _Stream:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cancelled = False
        self.sock: socket.socket | None = None  # http.client forgets it once the head is read
        self.status = self.sent = 0

    def bind(self, sock: socket.socket) -> None:
        with self.lock:
            self.sock = sock
        self.check()

    def check(self) -> None:
        if self.cancelled:
            raise _Cancelled

    def cancel(self) -> None:
        with self.lock:
            self.cancelled = True
            sock = self.sock
        if sock is not None:  # unblocks a read in the handler thread, which then closes it
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)


class _Link:
    """One WebSocket and the streams in flight on it. A new connection gets a new link."""

    def __init__(self, ws: wsclient.WebSocket) -> None:
        self.ws, self.lock = ws, threading.Lock()
        self.streams: dict[int, _Stream] = {}

    def start(self, stream: int) -> _Stream:
        with self.lock:
            return self.streams.setdefault(stream, _Stream())

    def finish(self, stream: int) -> None:
        with self.lock:
            self.streams.pop(stream, None)

    def cancel(self, stream: int) -> None:
        with self.lock:
            found = self.streams.get(stream)
        if found is not None:
            found.cancel()

    def drop(self) -> None:
        with self.lock:
            streams = list(self.streams.values())
        for found in streams:
            found.cancel()

    def send(self, frame: bytes) -> None:
        try:
            self.ws.send_binary(frame)  # wsclient serialises sends: this is the one send lock
        except (OSError, wsclient.WSError):
            raise _Cancelled from None


class _Ending:
    def __init__(self) -> None:
        self.close: int | None = None
        self.detail = ""
        self.ready_at: float | None = None

    def describe(self) -> str:
        parts = [f"close={self.close}"] if self.close is not None else []
        return " ".join([*parts, self.detail] if self.detail else parts) or "close=-"


def _clean_path(path: str) -> str:
    return path.partition("?")[0][:200]  # never the query string


class Connector:
    def __init__(
        self,
        settings: Settings,
        tz: tzinfo,
        *,
        timing: Timing = DEFAULT_TIMING,
        clock: Callable[[], float] = time.monotonic,
        rand: Callable[[], float] = random.random,
        sleep: Callable[[float], object] | None = None,
        now: Callable[[], datetime] | None = None,
        out: TextIO | None = None,
        connect: Callable[..., wsclient.WebSocket] = wsclient.connect,
    ) -> None:
        self.settings, self.tz, self.timing = settings, tz, timing
        self._clock, self._rand, self._connect, self._out = clock, rand, connect, out
        self._now = now or (lambda: datetime.now(tz))
        self._stop = threading.Event()
        self._sleep = sleep or self._stop.wait
        self._log_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=POOL, thread_name_prefix="relay")

    def stop(self) -> None:
        self._stop.set()

    def _log(self, text: str) -> None:
        stamp = timefmt.format_time(self._now().astimezone(self.tz))
        with self._log_lock:
            print(f"{stamp} {text}", file=self._out or sys.stderr, flush=True)

    # -- connection lifecycle ----------------------------------------------------------------

    def run(self) -> dict[str, object]:
        """Connect and serve until stopped. Fatal closes raise a BrandcalError (exit 2, 4 or 8)."""
        backoff = Backoff(self._rand)
        try:
            while not self._stop.is_set():
                ending = self._attempt()
                if self._stop.is_set():
                    self._log("disconnect close=1000 backoff=none")
                    break
                up = 0.0 if ending.ready_at is None else self._clock() - ending.ready_at
                delay = backoff.next(up)
                self._log(f"disconnect {ending.describe()} backoff={delay:.2f}s")
                self._sleep(delay)
        finally:
            self._pool.shutdown(wait=False, cancel_futures=True)
        return {"ok": True, "stopped": True}

    def _attempt(self) -> _Ending:
        s, ending = self.settings, _Ending()
        extra = {}
        if s.access is not None:
            extra = {"CF-Access-Client-Id": s.access[0], "CF-Access-Client-Secret": s.access[1]}
        try:
            ws = self._connect(s.url, headers=extra, timeout=self.timing.handshake)
        except wsclient.HandshakeRefused as err:
            if err.status in (401, 403):
                raise _refused() from None
            ending.detail = f"status={err.status}"
            return ending
        except (OSError, wsclient.WSError) as err:
            ending.detail = f"error={type(err).__name__}"
            return ending
        link = _Link(ws)
        try:
            self._handshake(ws)
            ending.ready_at = self._clock()
            self._log("connected ready")
            self._serve(link)
            ending.close = 1000
        except wsclient.Closed as err:
            _fatal(err.code)
            ending.close = err.code
        except (OSError, wsclient.WSError, FrameError, Stale) as err:
            ending.detail = f"error={type(err).__name__}"
        finally:
            link.drop()
            ws.abort()
        return ending

    def _expect(self, ws: wsclient.WebSocket, kind: int) -> Frame:
        end = self._clock() + self.timing.handshake
        while (left := end - self._clock()) > 0:
            message = ws.recv(left)
            if isinstance(message, bytes):
                frame = decode(message)
                if frame.kind != kind:
                    raise FrameError("the handshake frames are out of order")
                return frame
        raise Stale

    def _handshake(self, ws: wsclient.WebSocket) -> None:
        hello = _json({"v": 1, "agent": f"brandcal-relay/{__version__}"})
        ws.send_binary(encode(HELLO, 0, hello))
        nonce = self._expect(ws, CHALLENGE).payload
        ws.send_binary(encode(PROOF, 0, proof(self.settings.secret, nonce)))
        if decode_json(self._expect(ws, READY).payload).get("v") != 1:
            raise BrandcalError(
                ErrorCode.PROTOCOL_MISMATCH,
                "The relay answered with a protocol version this brandcal does not speak.",
                "Update brandcal or the Worker so both speak protocol v1.",
            )

    def _serve(self, link: _Link) -> None:
        ws, t, clock = link.ws, self.timing, self._clock
        last_rx = last_ping = last_text = clock()
        seen = ws.frames
        while not self._stop.is_set():
            message = ws.recv(t.tick)
            now = clock()
            if ws.frames != seen:
                seen, last_rx = ws.frames, now
            if isinstance(message, bytes):
                self._dispatch(link, decode(message))
            if now - last_rx >= t.stale:
                raise Stale
            if now - last_ping >= t.ping:
                ws.ping()
                last_ping = now
            if now - last_text >= t.text_ping:
                ws.send_text("ping")
                last_text = now
        ws.close(1000)

    def _dispatch(self, link: _Link, frame: Frame) -> None:
        if frame.kind == REQ:
            found = link.start(frame.stream)
            self._pool.submit(self._handle, link, frame.stream, found, frame.payload)
        elif frame.kind == CANCEL:
            link.cancel(frame.stream)

    # -- one request ---------------------------------------------------------------------------

    def _handle(self, link: _Link, stream: int, found: _Stream, payload: bytes) -> None:
        began, method, path, outcome = self._clock(), "-", "-", "ok"
        try:
            req = decode_req(payload)
            headers = self._check(req)
            method, path = req.method, _clean_path(req.path)
            self._forward(link, found, stream, req, headers)
        except _Cancelled:
            outcome = "cancelled"
        except (_Refuse, FrameError) as err:
            outcome = err.code if isinstance(err, _Refuse) else "BAD_FRAME"
            self._reply_error(link, stream, outcome)
        except Exception as err:  # a bug here must not kill the pool thread or the socket
            outcome = f"error={type(err).__name__}"
            self._reply_error(link, stream, "UPSTREAM_DOWN")
        finally:
            link.finish(stream)
            ms = int((self._clock() - began) * 1000)
            self._log(
                f"stream={stream} method={method} path={path} status={found.status}"
                f" ms={ms} bytes={found.sent} outcome={outcome}"
            )

    @staticmethod
    def _reply_error(link: _Link, stream: int, code: str) -> None:
        with contextlib.suppress(_Cancelled):
            link.send(encode(RES_ERR, stream, _json({"code": code})))

    def _check(self, req: Request) -> list[tuple[str, str]]:
        """Refuse what must not reach brandcal; return the request headers to replay."""
        bad = _Refuse("BAD_FRAME")
        if req.method not in ("GET", "POST") or not req.path.startswith("/"):
            raise bad
        if _BAD_PATH.search(req.path) or not req.path.isascii():
            raise bad
        hosts = [v for k, v in req.headers if k.lower() == "host"]
        if hosts != [self.settings.public_host]:
            raise bad
        kept = [(k, v) for k, v in req.headers if k.lower() in REQUEST_HEADERS]
        if not all(_TOKEN.fullmatch(k) and not _BAD_VALUE.search(v) for k, v in kept):
            raise bad
        return kept

    def _arm(self, sock: socket.socket, deadline: float) -> None:
        left = deadline - self._clock()
        if left <= 0:
            raise _Refuse("UPSTREAM_TIMEOUT")
        sock.settimeout(left)

    def _forward(
        self,
        link: _Link,
        found: _Stream,
        stream: int,
        req: Request,
        headers: list[tuple[str, str]],
    ) -> None:
        s, cap = self.settings, self.settings.max_response
        deadline = self._clock() + self.timing.response
        conn = http.client.HTTPConnection(UPSTREAM_HOST, s.port, timeout=self.timing.connect)
        try:
            try:
                conn.connect()
            except OSError:
                raise _Refuse("UPSTREAM_DOWN") from None
            sock = conn.sock
            if sock is None:
                raise _Refuse("UPSTREAM_DOWN")
            found.bind(sock)
            self._arm(sock, deadline)
            conn.putrequest(req.method, req.path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", s.public_host)
            for name, value in headers:
                conn.putheader(name, value)
            if req.method == "POST" or req.body:
                conn.putheader("Content-Length", str(len(req.body)))
            conn.endheaders(req.body)
            resp = conn.getresponse()
            kept = [(k, v) for k, v in resp.getheaders() if k.lower() in RESPONSE_HEADERS]
            try:
                length: int | None = int(resp.getheader("Content-Length") or "")
            except ValueError:
                length = None
            if length is not None and length > cap:
                raise _Refuse("TOO_LARGE")
            link.send(encode_res_head(stream, resp.status, kept, length))
            found.status = resp.status
            while not resp.isclosed():  # http.client closes it after the last byte
                found.check()
                self._arm(sock, deadline)
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                if found.sent + len(chunk) > cap:
                    raise _Refuse("TOO_LARGE")
                link.send(encode(RES_BODY, stream, chunk))
                found.sent += len(chunk)
            if length is not None and found.sent != length:
                raise _Refuse("UPSTREAM_DOWN")
            link.send(encode(RES_END, stream))
        except (_Refuse, _Cancelled):
            raise
        except TimeoutError:
            raise _Refuse("UPSTREAM_TIMEOUT") from None
        except (OSError, http.client.HTTPException, ValueError):
            found.check()
            raise _Refuse("UPSTREAM_DOWN") from None
        finally:
            conn.close()


def _refused() -> BrandcalError:
    return BrandcalError(
        ErrorCode.CONNECTOR_REFUSED,
        "The relay refused the connector's credentials.",
        "Check the access token and relay secret files; rotate them if they were revoked.",
    )


def _fatal(code: int) -> None:
    """Close codes that end the connector instead of reconnecting (spec 8)."""
    if code == 4003:
        raise _refused()
    if code == 4002:
        raise BrandcalError(
            ErrorCode.PROTOCOL_MISMATCH,
            "The relay does not speak protocol v1.",
            "Update brandcal or the Worker so both speak protocol v1.",
        )
    if code == 4001:
        raise BrandcalError(
            ErrorCode.CONNECTOR_REPLACED,
            "A newer connector took over the relay, so this one stopped.",
            "Run one `brandcal relay` only; do not restart this one.",
        )


def run(base: Path, cfg: Mapping[str, Any], local_dev: bool) -> dict[str, object]:
    """Check the config, read the secrets once, then relay until SIGTERM or SIGINT."""
    settings = load_settings(cfg, local_dev)
    connector = Connector(settings, display_tz(cfg))
    names = (signal.SIGTERM, signal.SIGINT)
    previous = {}
    if threading.current_thread() is threading.main_thread():
        previous = {n: signal.signal(n, lambda *_: connector.stop()) for n in names}
    print(f"brandcal relay: connecting to {urlsplit(settings.url).netloc}", file=sys.stderr)
    try:
        return connector.run()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
