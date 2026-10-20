"""Protocol v1 frames (spec 5) against the golden vectors shared with the Worker's tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import pytest

from brandcal import relay

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "data" / "relay_frames.json").read_text(encoding="utf-8")
)
KINDS = {
    name: getattr(relay, name)
    for name in (
        "HELLO CHALLENGE PROOF READY REQ CANCEL RES_HEAD RES_BODY RES_END RES_ERR".split()  # noqa: SIM905
    )
}


def ids(vectors: list[dict[str, Any]]) -> list[str]:
    return [v["name"] for v in vectors]


@pytest.mark.parametrize("vec", VECTORS["valid"], ids=ids(VECTORS["valid"]))
def test_valid_vectors_decode_and_encode_back(vec: dict[str, Any]) -> None:
    data = bytes.fromhex(vec["hex"])
    frame = relay.decode(data)
    assert (frame.kind, frame.stream) == (KINDS[vec["type"]], vec["stream"])
    if "json" in vec:
        assert relay.decode_json(frame.payload) == vec["json"]
    elif "req" in vec:
        req = relay.decode_req(frame.payload)
        want = vec["req"]
        assert (req.method, req.path) == (want["m"], want["p"])
        assert [list(h) for h in req.headers] == want["h"]
        assert req.body == bytes.fromhex(want["body_hex"])
        assert relay.encode_req(frame.stream, req.method, req.path, req.headers, req.body) == data
        return
    else:
        assert frame.payload == bytes.fromhex(vec["payload_hex"])
    assert relay.encode(frame.kind, frame.stream, frame.payload) == data


@pytest.mark.parametrize("vec", VECTORS["malformed"], ids=ids(VECTORS["malformed"]))
def test_malformed_vectors_are_refused(vec: dict[str, Any]) -> None:
    data = bytes.fromhex(vec["hex"])
    if vec["where"] == "frame":
        with pytest.raises(relay.FrameError):
            relay.decode(data)
    else:
        frame = relay.decode(data)  # the frame is fine; the REQ payload is not
        with pytest.raises(relay.FrameError):
            relay.decode_req(frame.payload)


def test_a_frame_over_one_mib_is_refused_both_ways() -> None:
    limit = VECTORS["max_frame"]
    assert limit == relay.MAX_FRAME == 1024 * 1024
    ok = relay.encode(relay.RES_BODY, 1, b"x" * (limit - 5))
    assert len(ok) == limit and relay.decode(ok).stream == 1
    with pytest.raises(relay.FrameError):
        relay.encode(relay.RES_BODY, 1, b"x" * (limit - 4))
    with pytest.raises(relay.FrameError):
        relay.decode(ok + b"x")


def test_the_head_is_type_then_stream_big_endian() -> None:
    assert relay.encode(relay.RES_END, 0x01020304) == bytes([0x22, 1, 2, 3, 4])


def test_res_head_encodes_unknown_length_as_null() -> None:
    frame = relay.decode(relay.encode_res_head(5, 200, [("Allow", "GET, POST")], None))
    assert relay.decode_json(frame.payload) == {"s": 200, "h": [["Allow", "GET, POST"]], "bl": None}


def test_hmac_proof_matches_the_vector_and_an_independent_hmac() -> None:
    p = VECTORS["proof"]
    secret, nonce = p["secret"].encode(), bytes.fromhex(p["nonce_hex"])
    assert p["label"] == "brandcal-relay.v1"
    assert relay.proof(secret, nonce).hex() == p["hmac_hex"]
    assert (
        hmac.new(secret, nonce + b"brandcal-relay.v1", hashlib.sha256).hexdigest() == p["hmac_hex"]
    )


def test_proof_depends_on_secret_and_nonce() -> None:
    nonce = bytes(32)
    base = relay.proof(b"one", nonce)
    assert len(base) == 32
    assert relay.proof(b"two", nonce) != base
    assert relay.proof(b"one", b"\x01" * 32) != base
