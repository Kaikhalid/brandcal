"""The minimal RFC 6455 client (spec 4, 10): handshake, framing, limits and close codes."""

from __future__ import annotations

import struct
import threading
from collections.abc import Callable, Iterator

import pytest
from ws_env import Peer, WSServer, wait_until

from brandcal import wsclient
from brandcal.wsclient import Closed, HandshakeRefused, WebSocket, WSError


@pytest.fixture
def serve() -> Iterator[Callable[..., WSServer]]:
    made: list[WSServer] = []

    def start(handler: Callable[[Peer], None], **kw: object) -> WSServer:
        made.append(WSServer(handler, **kw))  # type: ignore[arg-type]
        return made[-1]

    yield start
    for server in made:
        server.close()


def hold(peer: Peer) -> None:
    """Keep the connection open until the client goes away."""
    try:
        while True:
            peer.read_frame()
    except (OSError, EOFError):
        pass


def open_ws(server: WSServer, **kw: object) -> WebSocket:
    return wsclient.connect(server.url, timeout=2.0, **kw)  # type: ignore[arg-type]


def test_handshake_sends_key_subprotocol_and_extra_headers(serve: Callable[..., WSServer]) -> None:
    server = serve(hold)
    ws = open_ws(server, headers={"CF-Access-Client-Id": "id-1", "CF-Access-Client-Secret": "s-1"})
    ws.abort()
    req = server.requests[0]
    h = req["headers"]
    assert req["line"] == "GET /_relay/connect HTTP/1.1"
    assert h["upgrade"] == "websocket" and h["sec-websocket-version"] == "13"
    assert h["sec-websocket-protocol"] == "brandcal-relay.v1"
    assert h["host"] == f"127.0.0.1:{server.port}"
    assert len(h["sec-websocket-key"]) == 24
    assert (h["cf-access-client-id"], h["cf-access-client-secret"]) == ("id-1", "s-1")
    assert "sec-websocket-extensions" not in h


def test_each_connection_uses_a_fresh_key(serve: Callable[..., WSServer]) -> None:
    server = serve(hold)
    for _ in range(2):
        open_ws(server).abort()
    keys = {r["headers"]["sec-websocket-key"] for r in server.requests}
    assert len(keys) == 2


@pytest.mark.parametrize("status", [401, 403, 530])
def test_a_refused_upgrade_surfaces_the_status(serve: Callable[..., WSServer], status: int) -> None:
    server = serve(hold, refuse=status)
    with pytest.raises(HandshakeRefused) as err:
        open_ws(server)
    assert err.value.status == status


@pytest.mark.parametrize(
    "options",
    [
        {"bad_accept": True},
        {"extensions": "permessage-deflate"},
        {"protocol": "other.v1"},
        {"protocol": None},
    ],
)
def test_a_bad_handshake_answer_is_refused(
    serve: Callable[..., WSServer], options: dict[str, object]
) -> None:
    with pytest.raises(WSError):
        open_ws(serve(hold, **options))


def test_header_injection_is_refused_before_connecting() -> None:
    with pytest.raises(WSError):
        wsclient.connect("ws://127.0.0.1:1/x", headers={"X-A": "b\r\nX-Evil: 1"})
    with pytest.raises(WSError):
        wsclient.connect("http://127.0.0.1:1/x")


def test_sent_frames_are_masked_and_complete(serve: Callable[..., WSServer]) -> None:
    seen: list[tuple[int, bytes, bool, bool]] = []
    done = threading.Event()

    def handler(peer: Peer) -> None:
        for _ in range(3):
            seen.append(peer.read_frame())
        done.set()
        hold(peer)

    ws = open_ws(serve(handler))
    ws.send_binary(b"\x00\x01" * 100_000)  # 200 kB: the 64-bit length form
    ws.send_text("héllo")
    ws.ping(b"p")
    assert done.wait(3)
    ws.abort()
    assert [(op, fin, masked) for op, _, fin, masked in seen] == [
        (2, True, True),
        (1, True, True),
        (9, True, True),
    ]
    assert seen[0][1] == b"\x00\x01" * 100_000
    assert seen[1][1] == "héllo".encode()
    assert seen[2][1] == b"p"


def test_receives_text_binary_and_answers_ping(serve: Callable[..., WSServer]) -> None:
    pong: list[tuple[int, bytes]] = []

    def handler(peer: Peer) -> None:
        peer.send(1, b"hi")
        peer.send(9, b"are-you-there")
        peer.send(2, b"\xff\x00")
        op, payload, _, masked = peer.read_frame()
        assert masked
        pong.append((op, payload))
        hold(peer)

    ws = open_ws(serve(handler))
    assert ws.recv(2) == "hi"
    assert ws.recv(2) == b"\xff\x00"  # the ping in between was answered, not returned
    wait_until(lambda: pong)
    ws.abort()
    assert pong == [(10, b"are-you-there")]
    assert ws.frames == 3


def test_fragmented_messages_are_joined_and_pings_may_interleave(
    serve: Callable[..., WSServer],
) -> None:
    def handler(peer: Peer) -> None:
        peer.send(1, b"he", fin=False)
        peer.send(9, b"x")
        peer.send(0, b"l", fin=False)
        peer.send(0, b"lo")
        peer.send(2, b"ab", fin=False)
        peer.send(0, b"cd")
        hold(peer)

    ws = open_ws(serve(handler))
    assert ws.recv(2) == "hello"
    assert ws.recv(2) == b"abcd"
    ws.abort()


def test_recv_times_out_without_losing_a_partial_frame(serve: Callable[..., WSServer]) -> None:
    go = threading.Event()

    def handler(peer: Peer) -> None:
        peer.sock.sendall(b"\x82\x05ab")  # a frame cut short
        go.wait(3)
        peer.sock.sendall(b"cde")
        hold(peer)

    ws = open_ws(serve(handler))
    assert ws.recv(0.05) is None
    go.set()
    assert ws.recv(2) == b"abcde"
    ws.abort()


def test_a_message_over_one_mib_is_refused(serve: Callable[..., WSServer]) -> None:
    limit = wsclient.MAX_MESSAGE

    def single(peer: Peer) -> None:
        peer.send(2, b"x" * (limit + 1))
        hold(peer)

    def pieces(peer: Peer) -> None:
        peer.send(2, b"x" * limit, fin=False)
        peer.send(0, b"y")
        hold(peer)

    def exact(peer: Peer) -> None:
        peer.send(2, b"x" * limit)
        hold(peer)

    for handler in (single, pieces):
        ws = open_ws(serve(handler))
        with pytest.raises(WSError, match="1 MiB"):
            ws.recv(2)
        ws.abort()
    ws = open_ws(serve(exact))
    assert ws.recv(3) == b"x" * limit
    ws.abort()


@pytest.mark.parametrize(
    "send",
    [
        lambda p: p.send(2, b"x", rsv=0x40),
        lambda p: p.send(2, b"x", rsv=0x10),
        lambda p: p.send(3, b"x"),
        lambda p: p.send(0, b"x"),
        lambda p: p.send(9, b"x", fin=False),
        lambda p: p.send(9, b"x" * 126),
        lambda p: p.send(1, b"\xff\xfe"),
        lambda p: p.sock.sendall(b"\x82\x81abcdx"),  # a masked frame from the server
        lambda p: (p.send(1, b"a", fin=False), p.send(1, b"b")),
        lambda p: p.send(8, b"\x03"),
    ],
    ids=[
        "rsv1",
        "rsv3",
        "reserved-opcode",
        "orphan-continuation",
        "fragmented-control",
        "long-control",
        "bad-utf8",
        "server-masked",
        "interleaved-messages",
        "one-byte-close",
    ],
)
def test_protocol_violations_are_refused(
    serve: Callable[..., WSServer], send: Callable[[Peer], object]
) -> None:
    def handler(peer: Peer) -> None:
        send(peer)
        hold(peer)

    ws = open_ws(serve(handler))
    with pytest.raises(WSError):
        ws.recv(2)
    ws.abort()


def test_close_frame_is_echoed_and_reported(serve: Callable[..., WSServer]) -> None:
    echoed: list[tuple[int, bytes]] = []

    def handler(peer: Peer) -> None:
        peer.close(4001, "replaced")
        op, payload, _, _ = peer.read_frame()
        echoed.append((op, payload))

    ws = open_ws(serve(handler))
    with pytest.raises(Closed) as err:
        ws.recv(2)
    assert (err.value.code, err.value.reason) == (4001, "replaced")
    assert ws.closed
    wait_until(lambda: echoed)
    assert echoed[0][0] == 8 and struct.unpack(">H", echoed[0][1][:2])[0] == 4001


def test_close_without_a_code_and_a_dropped_connection(serve: Callable[..., WSServer]) -> None:
    ws = open_ws(serve(lambda peer: peer.send(8)))
    with pytest.raises(Closed) as err:
        ws.recv(2)
    assert err.value.code == 1005
    gone = open_ws(serve(lambda peer: None))
    with pytest.raises(Closed) as err:
        gone.recv(2)
    assert err.value.code == 1006


def test_close_sends_the_code(serve: Callable[..., WSServer]) -> None:
    got: list[bytes] = []
    done = threading.Event()

    def handler(peer: Peer) -> None:
        got.append(peer.read_frame()[1])
        done.set()

    ws = open_ws(serve(handler))
    ws.close(1000)
    assert done.wait(3)
    assert struct.unpack(">H", got[0])[0] == 1000
