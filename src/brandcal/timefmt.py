"""Time parsing and formatting (SPEC 5.2). Never consults the machine's timezone."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from brandcal.errors import BrandcalError, ErrorCode

_OFFSET = re.compile(r"([+-])(\d{2}):(\d{2})")
_TIME = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(?::\d{2})?)(Z|[+-]\d{2}:\d{2})?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _offset(value: str) -> tzinfo | None:
    if value == "Z":
        return UTC
    m = _OFFSET.fullmatch(value)
    if m is None or int(m[2]) > 23 or int(m[3]) > 59:
        return None
    delta = timedelta(hours=int(m[2]), minutes=int(m[3]))
    return timezone(-delta if m[1] == "-" else delta)


def resolve_tz(value: str) -> tzinfo:
    """Return a tzinfo for an IANA name or a fixed offset ("+03:00", "Z")."""
    value = value.strip()
    if not value:
        raise BrandcalError(
            ErrorCode.TZ_NOT_CONFIGURED,
            "No display timezone is configured.",
            'Set "timezone" in config.json or BRANDCAL_TZ.',
        )
    fixed = _offset(value)
    if fixed is not None:
        return fixed
    try:
        return ZoneInfo(value)
    except (ValueError, OSError, KeyError):
        raise BrandcalError(
            ErrorCode.BAD_ARGS,
            f"Unknown timezone: {value!r}.",
            "Use an IANA name such as Europe/London or an offset such as +03:00.",
        ) from None


def parse_time(text: str, tz: tzinfo) -> datetime:
    """Parse a time that carries an offset and convert it to tz."""
    m = _TIME.fullmatch(text.strip())
    if m is None:
        raise BrandcalError(
            ErrorCode.BAD_TIME, f"Cannot parse time: {text!r}.", "Use YYYY-MM-DDTHH:MM:SS+HH:MM."
        )
    if m[3] is None:
        raise BrandcalError(
            ErrorCode.TIME_OFFSET_REQUIRED,
            f"Time has no UTC offset: {text!r}.",
            "Add an offset such as +03:00 or Z.",
        )
    try:
        dt = datetime.fromisoformat(f"{m[1]}T{m[2]}").replace(tzinfo=_offset(m[3]))
    except ValueError:
        raise BrandcalError(ErrorCode.BAD_TIME, f"Cannot parse time: {text!r}.") from None
    return dt.astimezone(tz)


def format_time(dt: datetime) -> str:
    """Format as YYYY-MM-DDTHH:MM:SS+HH:MM (never "Z")."""
    if dt.utcoffset() is None:
        raise ValueError("naive datetime has no offset")
    return dt.replace(microsecond=0).isoformat(timespec="seconds")


def normalise_time(text: str, tz: tzinfo) -> str:
    return format_time(parse_time(text, tz))


def parse_window(text: str, tz: tzinfo) -> tuple[datetime, datetime]:
    """Parse "START/END": start before end, both on one local date in tz."""
    parts = text.split("/")
    if len(parts) != 2:
        raise BrandcalError(
            ErrorCode.BAD_WINDOW, f"Window must be START/END: {text!r}.", "Use START/END."
        )
    start, end = parse_time(parts[0], tz), parse_time(parts[1], tz)
    if end <= start:
        raise BrandcalError(ErrorCode.BAD_WINDOW, "Window end must be after its start.")
    if start.date() != end.date():
        raise BrandcalError(
            ErrorCode.BAD_WINDOW, "Window must fall within one local date in the display timezone."
        )
    return start, end


def normalise_window(text: str, tz: tzinfo) -> str:
    start, end = parse_window(text, tz)
    return f"{format_time(start)}/{format_time(end)}"


def parse_date(text: str) -> date:
    """Parse YYYY-MM-DD only."""
    try:
        if _DATE.fullmatch(text.strip()):
            return date.fromisoformat(text.strip())
    except ValueError:
        pass
    raise BrandcalError(ErrorCode.BAD_TIME, f"Cannot parse date: {text!r}.", "Use YYYY-MM-DD.")


def to_utc_text(dt: datetime) -> str:
    """UTC text in the same format as SQLite datetime()."""
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def local_date(dt: datetime, tz: tzinfo) -> date:
    return dt.astimezone(tz).date()


def month_start(dt: datetime, tz: tzinfo) -> datetime:
    """Local midnight on the 1st of dt's month in tz."""
    local = dt.astimezone(tz)
    return datetime(local.year, local.month, 1, tzinfo=tz)


def month_key(dt: datetime, tz: tzinfo) -> str:
    return dt.astimezone(tz).strftime("%Y-%m")
