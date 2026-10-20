"""A minimal RFC 6455 WebSocket client for `brandcal relay`, stdlib only.

Deliberately narrow: client role only, no extensions (a server that offers one is refused), one
fixed subprotocol, masked frames out, fragmented messages accepted in, RSV bits refused, and no
inbound message over 1 MiB. Sends are thread-safe; ``recv`` belongs to one thread.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import select
import socket
import ssl
import struct
import threading
import time
from collections.abc import Mapping
from urllib.parse import urlsplit

SUBPROTOCOL = "brandcal-relay.v1"
MAX_MESSAGE = 1024 * 1024
SEND_TIMEOUT = 30.0  # a send to a dead peer must not hang forever
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_CONT, _TEXT, _BINARY, _CLOSE, _PING, _PONG = 0, 1, 2, 8, 9, 10
_HEAD_LIMIT = 16 * 1024


class WSError(Exception):
    """The handshake failed or the peer broke the protocol."""


class HandshakeRefused(WSError):
    """The server answered the upgrade with an HTTP status other than 101."""

    def __init__(self, status: int) -> None:
        super().__init__(f"the upgrade was refused with HTTP {status}")
        self.status = status


class Closed(Exception):
    """The connection ended: a close frame (its code) or a dropped connection (1006)."""

    def __init__(self, code: int, reason: str = "") -> None:
        super().__init__(f"closed with code {code}")
        self.code, self.reason = code, reason


def _mask(data: bytes, key: bytes) -> bytes:
    if not data:
        return data
    pad = (key * (len(data) // 4 + 1))[: len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(pad, "big")).to_bytes(len(data), "big")


class WebSocket:
    def __init__(self, sock: socket.socket, leftover: bytes = b"") -> None:
        self._sock = sock
        self._buf = bytearray(leftover)
        self._send_lock = threading.Lock()
        self._kind = 0  # opcode of the fragmented message being assembled, 0 if none
        self._parts: list[bytes] = []
        self._size = 0
        self.frames = 0  # every frame received, control frames included (liveness)
        self.closed = False

    # -- sending --------------------------------------------------------------------------

    def _write(self, opcode: int, payload: bytes = b"") -> None:
        n = len(payload)
        if n < 126:
            head = bytes([0x80 | opcode, 0x80 | n])
        elif n < 65536:
            head = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", n)
        else:
            head = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", n)
        key = os.urandom(4)
        with self._send_lock:
            self._sock.sendall(head + key + _mask(payload, key))

    def send_binary(self, data: bytes) -> None:
        self._write(_BINARY, data)

    def send_text(self, text: str) -> None:
        self._write(_TEXT, text.encode())

    def ping(self, payload: bytes = b"") -> None:
        self._write(_PING, payload)

    def close(self, code: int = 1000) -> None:
        """Send a close frame, then drop the connection."""
        with contextlib.suppress(OSError):
            self._write(_CLOSE, struct.pack(">H", code))
        self.abort()

    def abort(self) -> None:
        """Drop the connection now; also unblocks a ``recv`` in another thread."""
        self.closed = True
        with contextlib.suppress(OSError):
            self._sock.shutdown(socket.SHUT_RDWR)
        self._sock.close()

    # -- receiving ------------------------------------------------------------------------

    def _frame(self) -> tuple[bool, int, bytes] | None:
        """One whole frame from the buffer, or None if it has not all arrived yet."""
        b = self._buf
        if len(b) < 2:
            return None
        if b[0] & 0x70:
            raise WSError("a frame has reserved bits set (no extension was negotiated)")
        if b[1] & 0x80:
            raise WSError("the server sent a masked frame")
        opcode, n, at = b[0] & 0x0F, b[1] & 0x7F, 2
        if opcode not in (_CONT, _TEXT, _BINARY, _CLOSE, _PING, _PONG):
            raise WSError(f"unknown opcode {opcode}")
        if n == 126 or n == 127:
            at = 4 if n == 126 else 10
            if len(b) < at:
                return None
            n = struct.unpack(">H" if at == 4 else ">Q", bytes(b[2:at]))[0]
        fin = bool(b[0] & 0x80)
        if opcode >= _CLOSE and (not fin or n > 125):
            raise WSError("a control frame is fragmented or too long")
        if n > MAX_MESSAGE:
            raise WSError("a message is over 1 MiB")
        if len(b) < at + n:
            return None
        payload = bytes(b[at : at + n])
        del b[: at + n]
        return fin, opcode, payload

    def _readable(self, wait: float | None) -> bool:
        if isinstance(self._sock, ssl.SSLSocket) and self._sock.pending():
            return True
        return bool(select.select([self._sock], [], [], wait)[0])

    def recv(self, timeout: float | None = None) -> bytes | str | None:
        """The next text (str) or binary (bytes) message; None if none arrived within ``timeout``.

        Pings are answered and pongs swallowed here (both count in ``frames``). A close frame is
        echoed and raised as ``Closed``; a dropped connection is ``Closed(1006)``.
        """
        end = None if timeout is None else time.monotonic() + timeout
        while True:
            frame = self._frame()
            if frame is None:
                wait = None if end is None else max(0.0, end - time.monotonic())
                if not self._readable(wait):
                    return None
                chunk = self._sock.recv(65536)
                if not chunk:
                    self.closed = True
                    raise Closed(1006, "connection lost")
                self._buf += chunk
                continue
            message = self._handle(*frame)
            if message is not None:
                return message

    def _handle(self, fin: bool, opcode: int, payload: bytes) -> bytes | str | None:
        self.frames += 1
        if opcode == _PING:
            self._write(_PONG, payload)
            return None
        if opcode == _PONG:
            return None
        if opcode == _CLOSE:
            if len(payload) == 1:
                raise WSError("a close frame has a one-byte payload")
            code = struct.unpack(">H", payload[:2])[0] if payload else 1005
            with contextlib.suppress(OSError):
                self._write(_CLOSE, payload[:2])
            self.abort()
            raise Closed(code, payload[2:].decode("utf-8", "replace"))
        if opcode == _CONT:
            if not self._kind:
                raise WSError("a continuation frame has nothing to continue")
        elif self._kind:
            raise WSError("a new message started inside a fragmented one")
        else:
            self._kind = opcode
        self._size += len(payload)
        if self._size > MAX_MESSAGE:
            raise WSError("a message is over 1 MiB")
        self._parts.append(payload)
        if not fin:
            return None
        data, kind = b"".join(self._parts), self._kind
        self._kind, self._parts, self._size = 0, [], 0
        if kind == _BINARY:
            return data
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise WSError("a text message is not valid UTF-8") from None


def _read_head(sock: socket.socket) -> tuple[bytes, bytes]:
    raw = b""
    while b"\r\n\r\n" not in raw:
        chunk = sock.recv(4096)
        if not chunk:
            raise WSError("the server closed the connection during the handshake")
        raw += chunk
        if len(raw) > _HEAD_LIMIT:
            raise WSError("the handshake answer is too long")
    head, _, rest = raw.partition(b"\r\n\r\n")
    return head, rest


def _check_answer(head: bytes, key: str) -> None:
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise WSError("the handshake answer is not HTTP")
    if int(parts[1]) != 101:
        raise HandshakeRefused(int(parts[1]))
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = (
            headers.get(name.strip().lower(), "") + " " + value
        ).strip()
    accept = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
    if headers.get("upgrade", "").lower() != "websocket":
        raise WSError("the server did not upgrade to websocket")
    if "upgrade" not in headers.get("connection", "").lower():
        raise WSError("the server answer has no Connection: Upgrade")
    if headers.get("sec-websocket-accept") != accept:
        raise WSError("Sec-WebSocket-Accept does not match the key")
    if "sec-websocket-extensions" in headers:
        raise WSError("the server offered an extension, and none was requested")
    if headers.get("sec-websocket-protocol") != SUBPROTOCOL:
        raise WSError(f"the server did not select the {SUBPROTOCOL} subprotocol")


def connect(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    context: ssl.SSLContext | None = None,
) -> WebSocket:
    """Open ``ws://`` or ``wss://`` (certificates and host name are always checked)."""
    u = urlsplit(url)
    if u.scheme not in ("ws", "wss") or not u.hostname:
        raise WSError("the URL must be ws:// or wss:// with a host")
    extra = dict(headers or {})
    if any(c in k + v for k, v in extra.items() for c in "\r\n\0"):
        raise WSError("a request header holds a CR, LF or NUL")
    secure = u.scheme == "wss"
    target = (u.path or "/") + (f"?{u.query}" if u.query else "")
    host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
    key = base64.b64encode(os.urandom(16)).decode()
    lines = [
        f"GET {target} HTTP/1.1",
        f"Host: {host}{f':{u.port}' if u.port else ''}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
        f"Sec-WebSocket-Protocol: {SUBPROTOCOL}",
        *(f"{k}: {v}" for k, v in extra.items()),
    ]
    raw = socket.create_connection((u.hostname, u.port or (443 if secure else 80)), timeout)
    sock: socket.socket = raw
    try:
        if secure:
            sock = (context or ssl.create_default_context()).wrap_socket(
                raw, server_hostname=u.hostname
            )
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        head, rest = _read_head(sock)
        _check_answer(head, key)
    except BaseException:
        sock.close()
        raw.close()
        raise
    sock.settimeout(SEND_TIMEOUT)
    return WebSocket(sock, rest)
