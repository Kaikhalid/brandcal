from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from brandcal.errors import BrandcalError, ErrorCode
from brandcal.timefmt import (
    format_time,
    local_date,
    month_key,
    month_start,
    normalise_time,
    normalise_window,
    parse_date,
    parse_time,
    parse_window,
    resolve_tz,
    to_utc_text,
)

PLUS3 = resolve_tz("+03:00")


def code_of(exc: pytest.ExceptionInfo[BrandcalError]) -> ErrorCode:
    return exc.value.code


def test_offset_required() -> None:
    with pytest.raises(BrandcalError) as exc:
        parse_time("2026-10-19T08:00:00", PLUS3)
    assert code_of(exc) == ErrorCode.TIME_OFFSET_REQUIRED
    assert exc.value.exit_code == 3


@pytest.mark.parametrize("text", ["", "tomorrow", "2026-13-40T00:00:00Z", "2026-10-19"])
def test_bad_time(text: str) -> None:
    with pytest.raises(BrandcalError) as exc:
        parse_time(text, PLUS3)
    assert code_of(exc) == ErrorCode.BAD_TIME


@pytest.mark.parametrize(
    ("tz", "expected"),
    [
        ("+03:00", "2026-10-19T08:00:00+03:00"),
        ("-05:00", "2026-10-19T00:00:00-05:00"),
        ("Z", "2026-10-19T05:00:00+00:00"),
    ],
)
def test_normalise_converts(tz: str, expected: str) -> None:
    assert normalise_time("2026-10-19T05:00:00Z", resolve_tz(tz)) == expected


def test_london_follows_dst() -> None:
    london = resolve_tz("Europe/London")
    assert normalise_time("2026-07-01T12:00:00Z", london) == "2026-07-01T13:00:00+01:00"
    assert normalise_time("2026-01-01T12:00:00Z", london) == "2026-01-01T12:00:00+00:00"


def test_seconds_optional_on_input() -> None:
    assert normalise_time("2026-10-19T08:00+03:00", PLUS3) == "2026-10-19T08:00:00+03:00"


def test_format_time_rejects_naive() -> None:
    with pytest.raises(ValueError):
        format_time(datetime(2026, 10, 19, 8, 0))


def test_format_time_drops_microseconds_and_z() -> None:
    dt = datetime(2026, 10, 19, 8, 0, 0, 123, tzinfo=UTC)
    assert format_time(dt) == "2026-10-19T08:00:00+00:00"


def test_window_valid() -> None:
    text = "2026-10-19T09:00Z/2026-10-19T10:30:00Z"
    assert normalise_window(text, UTC) == "2026-10-19T09:00:00+00:00/2026-10-19T10:30:00+00:00"
    start, end = parse_window(text, UTC)
    assert end - start == timedelta(minutes=90)


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-19T09:00:00Z",
        "2026-10-19T09:00:00Z/2026-10-19T10:00:00Z/2026-10-19T11:00:00Z",
        "2026-10-19T09:00:00Z/2026-10-19T09:00:00Z",
        "2026-10-19T09:00:00Z/2026-10-19T08:00:00Z",
        "2026-10-19T09:00:00Z/2026-10-20T09:00:00Z",
    ],
)
def test_bad_window(text: str) -> None:
    with pytest.raises(BrandcalError) as exc:
        parse_window(text, UTC)
    assert code_of(exc) == ErrorCode.BAD_WINDOW


def test_window_end_needs_offset() -> None:
    with pytest.raises(BrandcalError) as exc:
        parse_window("2026-10-19T09:00:00Z/2026-10-19T10:00:00", UTC)
    assert code_of(exc) == ErrorCode.TIME_OFFSET_REQUIRED


def test_window_spanning_dates_in_other_tz_rejected() -> None:
    text = "2026-10-19T18:00:00Z/2026-10-19T19:00:00Z"
    assert normalise_window(text, UTC).startswith("2026-10-19T18:00:00")
    with pytest.raises(BrandcalError) as exc:
        parse_window(text, resolve_tz("+05:30"))  # 23:30 -> 00:30 next day
    assert code_of(exc) == ErrorCode.BAD_WINDOW


def test_parse_date() -> None:
    assert parse_date("2026-10-19") == date(2026, 10, 19)
    for bad in ["2026-10-19T00:00:00Z", "20261019", "2026-02-30", ""]:
        with pytest.raises(BrandcalError) as exc:
            parse_date(bad)
        assert code_of(exc) == ErrorCode.BAD_TIME


def test_month_boundary_is_local() -> None:
    dt = parse_time("2026-11-01T01:00:00+03:00", PLUS3)
    assert month_start(dt, PLUS3) == datetime(2026, 11, 1, tzinfo=PLUS3)
    assert month_key(dt, PLUS3) == "2026-11"
    assert dt.astimezone(UTC).month == 10
    assert local_date(dt, PLUS3) == date(2026, 11, 1)


def test_month_key_converts_to_tz() -> None:
    dt = parse_time("2026-10-31T23:30:00+00:00", PLUS3)
    assert month_key(dt, PLUS3) == "2026-11"


def test_to_utc_text_matches_sqlite() -> None:
    dt = parse_time("2026-10-19T08:00:00+03:00", PLUS3)
    with sqlite3.connect(":memory:") as db:
        (expected,) = db.execute("SELECT datetime(?)", ("2026-10-19T08:00:00+03:00",)).fetchone()
    assert to_utc_text(dt) == expected == "2026-10-19 05:00:00"


def test_resolve_tz_errors() -> None:
    for value, code in [
        ("", ErrorCode.TZ_NOT_CONFIGURED),
        ("Not/AZone", ErrorCode.BAD_ARGS),
        ("+25:99", ErrorCode.BAD_ARGS),
    ]:
        with pytest.raises(BrandcalError) as exc:
            resolve_tz(value)
        assert code_of(exc) == code
