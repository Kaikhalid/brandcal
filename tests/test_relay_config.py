"""The `relay` config block, the secret files and `brandcal relay` as a command (spec 3, 8)."""

from __future__ import annotations

import io
import json
import os
import signal
import threading
from pathlib import Path
from typing import Any

import pytest
from ui_env import CFG, make_home
from ws_env import ACCESS, HOST, SECRET, TZ, FakeDO, Running, wait_until

from brandcal import cli, relay
from brandcal.errors import BrandcalError

ORIGIN = f"https://{HOST}"
TOKEN_TEXT = json.dumps({"client_id": ACCESS[0], "client_secret": ACCESS[1]})


def relay_cfg(
    tmp: Path, url: str = "wss://brandcal-relay.example.com/_relay/connect", **over: Any
) -> dict[str, Any]:
    (tmp / "secret").write_text(SECRET.decode() + "\n", encoding="utf-8")
    (tmp / "access.json").write_text(TOKEN_TEXT, encoding="utf-8")
    block: dict[str, Any] = {
        "url": url,
        "public_host": HOST,
        "secret_file": str(tmp / "secret"),
        "access_token_file": str(tmp / "access.json"),
        "max_response_mb": 32,
    }
    block.update(over)
    block = {k: v for k, v in block.items() if v is not None}
    serve = {"port": 8787, "allowed_origins": [ORIGIN]}
    return {**CFG, "serve": serve, "relay": block}


def relay_home(
    tmp: Path, monkeypatch: pytest.MonkeyPatch, url: str | None = None, **over: Any
) -> Path:
    home = make_home(tmp / "home", monkeypatch)
    cfg = relay_cfg(tmp, **over) if url is None else relay_cfg(tmp, url, **over)
    (home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return home


def refused(cfg: dict[str, Any], code: str, local_dev: bool = False) -> BrandcalError:
    with pytest.raises(BrandcalError) as err:
        relay.load_settings(cfg, local_dev)
    assert err.value.code == code and err.value.exit_code == 2
    return err.value


# -- settings ------------------------------------------------------------------------------------


def test_settings_are_read_and_the_secrets_stay_out_of_repr(tmp_path: Path) -> None:
    s = relay.load_settings(relay_cfg(tmp_path))
    assert (s.url, s.public_host, s.port) == (
        "wss://brandcal-relay.example.com/_relay/connect",
        HOST,
        8787,
    )
    assert s.secret == SECRET  # the trailing newline of the file is not part of it
    assert s.access == ACCESS
    assert s.max_response == 32 * 1024 * 1024
    assert SECRET.decode() not in repr(s) and ACCESS[1] not in repr(s)


def test_max_response_defaults_to_32_mib(tmp_path: Path) -> None:
    cfg = relay_cfg(tmp_path, max_response_mb=None)
    assert relay.load_settings(cfg).max_response == 32 * 1024 * 1024


@pytest.mark.parametrize(
    "url",
    [
        "ws://brandcal-relay.example.com/_relay/connect",
        "https://brandcal-relay.example.com/_relay/connect",
        "wss:///nohost",
        "wss://user:pw" + "@brandcal-relay.example.com/x",  # credentials in the URL
        "ws://127.0.0.1/x",
        "ws://localhost:8788/x",
        "ws://127.0.0.2:8788/x",
        "wss://[bad",
    ],
)
def test_the_url_must_be_wss(tmp_path: Path, url: str) -> None:
    refused(relay_cfg(tmp_path, url), "BAD_ARGS", local_dev=False)
    if url.startswith("ws://"):  # --local-dev opens only ws://127.0.0.1:PORT, nothing else
        refused(relay_cfg(tmp_path, url), "BAD_ARGS", local_dev=True)


def test_local_dev_allows_ws_on_loopback_and_a_missing_token(tmp_path: Path) -> None:
    cfg = relay_cfg(tmp_path, "ws://127.0.0.1:8788/_relay/connect")
    refused(cfg, "BAD_ARGS", local_dev=False)
    assert relay.load_settings(cfg, local_dev=True).url.startswith("ws://127.0.0.1:8788")
    (tmp_path / "access.json").unlink()
    assert relay.load_settings(cfg, local_dev=True).access is None
    cfg["relay"].pop("access_token_file")
    assert relay.load_settings(cfg, local_dev=True).access is None


def test_a_missing_token_is_only_allowed_with_local_dev_on_loopback(tmp_path: Path) -> None:
    cfg = relay_cfg(tmp_path)
    (tmp_path / "access.json").unlink()
    refused(cfg, "SECRET_UNAVAILABLE", local_dev=True)  # wss:// is not wrangler dev
    cfg["relay"].pop("access_token_file")
    refused(cfg, "BAD_ARGS", local_dev=True)


@pytest.mark.parametrize(
    "change",
    [
        {"public_host": "other.example.com"},
        {"public_host": ""},
        {"public_host": None},
        {"url": None},
        {"secret_file": None},
        {"max_response_mb": 0},
        {"max_response_mb": "32"},
        {"max_response_mb": True},
        {"max_response_mb": 5000},
        {"access_token_file": 7},
    ],
)
def test_other_bad_blocks_are_bad_args(tmp_path: Path, change: dict[str, Any]) -> None:
    cfg = relay_cfg(tmp_path)
    for key, value in change.items():
        if value is None:
            cfg["relay"].pop(key)
        else:
            cfg["relay"][key] = value
    refused(cfg, "BAD_ARGS")


def test_no_relay_block_and_no_serve_port_are_bad_args(tmp_path: Path) -> None:
    cfg = relay_cfg(tmp_path)
    refused({k: v for k, v in cfg.items() if k != "relay"}, "BAD_ARGS")
    cfg["serve"].pop("port")
    refused(cfg, "BAD_ARGS")


def test_public_host_matches_the_host_of_an_allowed_origin_including_a_port(tmp_path: Path) -> None:
    cfg = relay_cfg(tmp_path, public_host="localhost:3000")
    refused(cfg, "BAD_ARGS")
    cfg["serve"]["allowed_origins"] = [ORIGIN, "http://localhost:3000"]
    assert relay.load_settings(cfg).public_host == "localhost:3000"


# -- secret files ----------------------------------------------------------------------------------


def test_secret_problems_name_the_path_and_never_the_contents(tmp_path: Path) -> None:
    cfg = relay_cfg(tmp_path)
    (tmp_path / "access.json").write_text("not json but SUPER-SECRET-TEXT", encoding="utf-8")
    err = refused(cfg, "SECRET_UNAVAILABLE")
    assert str(tmp_path / "access.json") in err.message and "SUPER-SECRET-TEXT" not in str(
        err.to_dict()
    )


@pytest.mark.parametrize("which", ["secret", "access.json"])
def test_a_missing_or_unreadable_file_is_secret_unavailable(tmp_path: Path, which: str) -> None:
    cfg = relay_cfg(tmp_path)
    for how in ("missing", "directory"):
        target = tmp_path / which
        target.unlink()
        if how == "directory":
            target.mkdir()
        err = refused(cfg, "SECRET_UNAVAILABLE")
        assert str(target) in err.message
        if how == "directory":
            target.rmdir()
        target.write_text(SECRET.decode() if which == "secret" else TOKEN_TEXT, encoding="utf-8")


@pytest.mark.parametrize(
    "text",
    ["", "  \n", "[]", "{}", '{"client_id": "a"}', '{"client_id": 1, "client_secret": "b"}']
    + ['{"client_id": "a\\nb", "client_secret": "c"}', '{"client_id": "", "client_secret": "c"}'],
)
def test_an_empty_secret_or_a_malformed_token_is_secret_unavailable(
    tmp_path: Path, text: str
) -> None:
    cfg = relay_cfg(tmp_path)
    (tmp_path / "access.json").write_text(text, encoding="utf-8")
    refused(cfg, "SECRET_UNAVAILABLE")
    if not text.strip():
        (tmp_path / "access.json").write_text(TOKEN_TEXT, encoding="utf-8")
        (tmp_path / "secret").write_text(text, encoding="utf-8")
        refused(cfg, "SECRET_UNAVAILABLE")


def test_secrets_are_read_once_at_start_up(tmp_path: Path) -> None:
    do = FakeDO()
    cfg = relay_cfg(tmp_path, do.url)
    cfg["relay"].pop("access_token_file")
    settings = relay.load_settings(cfg, local_dev=True)
    (tmp_path / "secret").unlink()  # the store goes away after start-up
    running = Running(relay.Connector(settings, TZ, out=io.StringIO()))
    try:
        do.wait_ready()  # the in-memory copy still authenticates
    finally:
        running.stop()
        do.close()


def test_the_access_token_goes_out_as_the_two_cf_access_headers(tmp_path: Path) -> None:
    do = FakeDO()
    settings = relay.load_settings(relay_cfg(tmp_path, do.url), local_dev=True)
    running = Running(relay.Connector(settings, TZ, out=io.StringIO()))
    try:
        do.wait_ready()
        headers = do.server.requests[0]["headers"]
        assert (headers["cf-access-client-id"], headers["cf-access-client-secret"]) == ACCESS
        assert do.hello["v"] == 1 and do.hello["agent"].startswith("brandcal-relay/")
    finally:
        running.stop()
        do.close()


# -- the command ----------------------------------------------------------------------------------


def run(capsys: pytest.CaptureFixture[str], home: Path, *argv: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = cli.main(["--home", str(home), *argv])
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1  # one JSON line on exit
    parsed: dict[str, Any] = json.loads(out)
    return code, parsed


def test_help_lists_relay(capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert cli.main(["help", "relay"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "relay" and out["roles"] == ["admin"]
    assert "--local-dev" in out["arguments"] and "SECRET_UNAVAILABLE" in out["errors"]
    assert cli.main(["help"]) == 0
    assert "relay" in [c["name"] for c in json.loads(capsys.readouterr().out)["commands"]]


def test_only_an_admin_may_run_relay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = relay_home(tmp_path, monkeypatch)
    code, out = run(capsys, home, "relay", "--as", "manager-1")
    assert (code, out["error"]["code"]) == (4, "ROLE_NOT_ALLOWED")
    code, out = run(capsys, home, "relay")
    assert (code, out["error"]["code"]) == (2, "NO_AGENT")


def test_the_command_reports_secret_unavailable_on_stdout_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = relay_home(tmp_path, monkeypatch)
    (tmp_path / "secret").unlink()
    code, out = run(capsys, home, "relay", "--as", "admin-1")
    assert (code, out["error"]["code"]) == (2, "SECRET_UNAVAILABLE")
    assert str(tmp_path / "secret") in out["error"]["message"]


def test_a_bad_url_stops_before_any_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = relay_home(tmp_path, monkeypatch, "ws://127.0.0.1:9/x")
    code, out = run(capsys, home, "relay", "--as", "admin-1")
    assert (code, out["error"]["code"]) == (2, "BAD_ARGS")


@pytest.mark.parametrize(
    ("server", "code", "error"),
    [
        ({"close_after_ready": 4001}, 8, "CONNECTOR_REPLACED"),
        ({"close_after_ready": 4002}, 2, "PROTOCOL_MISMATCH"),
        ({"close_after_ready": 4003}, 4, "CONNECTOR_REFUSED"),
        ({"refuse": 401}, 4, "CONNECTOR_REFUSED"),
        ({"refuse": 403}, 4, "CONNECTOR_REFUSED"),
        ({"secret": b"a-different-secret"}, 4, "CONNECTOR_REFUSED"),  # the DO closes 4003
    ],
)
def test_exit_codes_for_the_fatal_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: dict[str, Any],
    code: int,
    error: str,
) -> None:
    do = FakeDO(**server)
    try:
        home = relay_home(tmp_path, monkeypatch, do.url)
        got, out = run(capsys, home, "relay", "--local-dev", "--as", "admin-1")
        assert (got, out["error"]["code"]) == (code, error)
        assert do.connections == (0 if server.get("refuse") else 1)  # never a reconnect
    finally:
        do.close()


def test_sigterm_and_sigint_close_with_1000_and_exit_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        do = FakeDO()
        before = signal.getsignal(sig)
        home = relay_home(tmp_path, monkeypatch, do.url)

        def signal_once_connected(d: FakeDO = do, s: signal.Signals = sig) -> None:
            d.wait_ready()
            os.kill(os.getpid(), s)

        threading.Thread(target=signal_once_connected, daemon=True).start()
        try:
            code, out = run(capsys, home, "relay", "--local-dev", "--as", "admin-1")
            assert (code, out) == (0, {"ok": True, "stopped": True})
            wait_until(lambda d=do: d.close_codes == [1000])  # type: ignore[misc]
            assert signal.getsignal(sig) is before  # the handlers are put back
        finally:
            do.close()
