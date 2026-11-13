"""In-process test servers for the relay: a raw WebSocket server, a fake Durable Object, and a
stub for `brandcal serve`. Stdlib only, loopback only, no network."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import os
import queue
import socket
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from brandcal import relay
from brandcal.wsclient import SUBPROTOCOL

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SECRET = b"test-relay-secret-not-real"
ACCESS = ("test-client-id.access", "test-client-secret-not-real")
HOST = "brandcal.example.com"
TZ = timezone(timedelta(hours=3))


def wait_until(check: Callable[[], object], timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < end, "timed out waiting for a condition"
        time.sleep(0.005)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Peer:
    """The server side of one WebSocket connection, speaking raw frames."""

    def __init__(self, sock: socket.socket, request: dict[str, Any], rest: bytes) -> None:
        self.sock, self.request, self.buf = sock, request, bytearray(rest)
        self.lock = threading.Lock()

    def _need(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def read_frame(self) -> tuple[int, bytes, bool, bool]:
        """(opcode, unmasked payload, fin, was_masked)."""
        b0, b1 = self._need(2)
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._need(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._need(8))[0]
        masked = bool(b1 & 0x80)
        key = self._need(4) if masked else b"\0\0\0\0"
        data = self._need(n)
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(data)) if masked else data
        return b0 & 0x0F, payload, bool(b0 & 0x80), masked

    def send(self, opcode: int, payload: bytes = b"", *, fin: bool = True, rsv: int = 0) -> None:
        n = len(payload)
        head = bytes([(0x80 if fin else 0) | rsv | opcode])
        if n < 126:
            head += bytes([n])
        elif n < 65536:
            head += bytes([126]) + struct.pack(">H", n)
        else:
            head += bytes([127]) + struct.pack(">Q", n)
        with self.lock:
            self.sock.sendall(head + payload)

    def close(self, code: int, reason: str = "") -> None:
        self.send(8, struct.pack(">H", code) + reason.encode())


class WSServer:
    """Accepts WebSocket upgrades on 127.0.0.1 and hands each connection to ``handler``."""

    def __init__(
        self,
        handler: Callable[[Peer], None],
        *,
        refuse: int | None = None,
        extensions: str | None = None,
        protocol: str | None = SUBPROTOCOL,
        bad_accept: bool = False,
    ) -> None:
        self.handler, self.refuse, self.extensions = handler, refuse, extensions
        self.protocol, self.bad_accept = protocol, bad_accept
        self.requests: list[dict[str, Any]] = []
        self.conns: list[socket.socket] = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.port = int(self.listener.getsockname()[1])
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/_relay/connect"

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            self.conns.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        try:
            raw = b""
            while b"\r\n\r\n" not in raw:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                raw += chunk
            head, _, rest = raw.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            headers = {
                k.strip().lower(): v.strip() for k, _, v in (x.partition(":") for x in lines[1:])
            }
            request = {"line": lines[0], "headers": headers}
            self.requests.append(request)
            if self.refuse:
                conn.sendall(
                    f"HTTP/1.1 {self.refuse} Refused\r\nContent-Length: 0\r\n\r\n".encode()
                )
                return
            digest = hashlib.sha1((headers["sec-websocket-key"] + GUID).encode()).digest()
            accept = (
                "AAAAAAAAAAAAAAAAAAAAAAAAAAA="
                if self.bad_accept
                else base64.b64encode(digest).decode()
            )
            out = [
                "HTTP/1.1 101 Switching Protocols",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Accept: {accept}",
            ]
            if self.protocol:
                out.append(f"Sec-WebSocket-Protocol: {self.protocol}")
            if self.extensions:
                out.append(f"Sec-WebSocket-Extensions: {self.extensions}")
            conn.sendall(("\r\n".join(out) + "\r\n\r\n").encode())
            self.handler(Peer(conn, request, rest))
        except (OSError, EOFError):
            pass
        finally:
            conn.close()

    def drop_all(self) -> None:
        for c in self.conns:
            with contextlib.suppress(OSError):
                c.shutdown(socket.SHUT_RDWR)

    def close(self) -> None:
        with contextlib.suppress(OSError):  # a bare close() would leave accept() blocked
            self.listener.shutdown(socket.SHUT_RDWR)
        self.listener.close()
        self.drop_all()


@dataclass
class Reply:
    status: int | None = None
    headers: list[list[str]] = field(default_factory=list)
    body: bytes = b""
    error: str | None = None
    kinds: list[int] = field(default_factory=list)


class FakeDO:
    """Speaks the DO side of protocol v1 and lets a test send requests through the connector."""

    def __init__(
        self,
        secret: bytes = SECRET,
        *,
        answer: bool = True,
        close_after_ready: int | None = None,
        **server: Any,
    ) -> None:
        self.secret, self.answer, self.close_after_ready = secret, answer, close_after_ready
        self.connections = self.pings = self.texts = 0
        self.close_codes: list[int] = []
        self.hello: dict[str, Any] = {}
        self.peer: Peer | None = None
        self.ready = threading.Event()
        self.streams: dict[int, queue.Queue[relay.Frame]] = {}
        self.next_stream = 1
        self.server = WSServer(self._handle, **server)

    @property
    def url(self) -> str:
        return self.server.url

    def _read(self, peer: Peer) -> relay.Frame | None:
        while True:
            op, payload, _, _ = peer.read_frame()
            if op == 2:
                return relay.decode(payload)
            if op == 1:
                self.texts += 1
                if self.answer:
                    peer.send(1, b"pong")
            elif op == 9:
                self.pings += 1
                if self.answer:
                    peer.send(10, payload)
            elif op == 8:
                self.close_codes.append(struct.unpack(">H", payload[:2])[0] if payload else 1005)
                peer.send(8, payload[:2])
                return None

    def _handle(self, peer: Peer) -> None:
        self.connections += 1
        hello = self._read(peer)
        assert hello is not None and hello.kind == relay.HELLO
        self.hello = relay.decode_json(hello.payload)
        nonce = os.urandom(32)
        peer.send(2, relay.encode(relay.CHALLENGE, 0, nonce))
        answer = self._read(peer)
        if answer is None:
            return
        if not hmac.compare_digest(answer.payload, relay.proof(self.secret, nonce)):
            peer.close(4003)
            return
        peer.send(2, relay.encode(relay.READY, 0, b'{"v":1,"max_streams":16}'))
        if self.close_after_ready is not None:
            peer.close(self.close_after_ready)
            return
        self.peer = peer
        self.ready.set()
        while (frame := self._read(peer)) is not None:
            if frame.stream in self.streams:
                self.streams[frame.stream].put(frame)

    def wait_ready(self) -> None:
        assert self.ready.wait(5), "no connector completed the handshake"

    def send_req(
        self, method: str, path: str, headers: list[tuple[str, str]], body: bytes = b""
    ) -> int:
        self.wait_ready()
        assert self.peer is not None
        stream, self.next_stream = self.next_stream, self.next_stream + 1
        self.streams[stream] = queue.Queue()
        self.peer.send(2, relay.encode_req(stream, method, path, headers, body))
        return stream

    def collect(self, stream: int, timeout: float = 5.0) -> Reply:
        reply = Reply()
        while True:
            frame = self.streams[stream].get(timeout=timeout)
            reply.kinds.append(frame.kind)
            if frame.kind == relay.RES_HEAD:
                head = relay.decode_json(frame.payload)
                reply.status, reply.headers = head["s"], head["h"]
            elif frame.kind == relay.RES_BODY:
                reply.body += frame.payload
            elif frame.kind == relay.RES_ERR:
                reply.error = relay.decode_json(frame.payload)["code"]
                return reply
            elif frame.kind == relay.RES_END:
                return reply

    def fetch(
        self,
        method: str,
        path: str,
        headers: list[tuple[str, str]] | None = None,
        body: bytes = b"",
    ) -> Reply:
        base = [("Host", HOST)] if headers is None else headers
        return self.collect(self.send_req(method, path, base, body))

    def cancel(self, stream: int) -> None:
        assert self.peer is not None
        self.peer.send(2, relay.encode(relay.CANCEL, stream))

    def close(self) -> None:
        self.server.close()


class Upstream:
    """A stand-in for `brandcal serve` that records what it receives."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []
        self.status = 200
        self.headers: list[tuple[str, str]] = [("Content-Type", "text/plain")]
        self.body = b"hello"
        self.close_delimited = False
        self.stall: threading.Event | None = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.serve(self)

            do_POST = do_GET

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = int(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()

    def serve(self, h: BaseHTTPRequestHandler) -> None:
        raw = h.rfile.read(int(h.headers.get("Content-Length") or 0))
        self.seen.append(
            {"method": h.command, "path": h.path, "headers": list(h.headers.items()), "body": raw}
        )
        if self.stall is not None:
            self.stall.wait(5)
        h.send_response(self.status)
        for key, value in self.headers:
            h.send_header(key, value)
        if not self.close_delimited:
            h.send_header("Content-Length", str(len(self.body)))
        h.end_headers()
        h.wfile.write(self.body)

    def header_names(self, index: int = 0) -> set[str]:
        return {k.lower() for k, _ in self.seen[index]["headers"]}

    def close(self) -> None:
        if self.stall is not None:
            self.stall.set()
        self.server.shutdown()
        self.server.server_close()


class Running:
    """A connector running in a thread."""

    def __init__(self, connector: relay.Connector) -> None:
        self.connector = connector
        self.result: dict[str, object] | None = None
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            self.result = self.connector.run()
        except BaseException as err:
            self.error = err

    def finish(self, timeout: float = 5.0) -> None:
        self.thread.join(timeout)
        assert not self.thread.is_alive(), "the connector did not stop"

    def stop(self) -> None:
        self.connector.stop()
        self.finish()
