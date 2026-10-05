"""Dravia State Bot - In-World Calendar

The Republic keeps its own era. Real-world dates are shifted by a constant
offset so that "today" falls in DRAVIA_CURRENT_YEAR (default 1985) and every
public record - Gazette, news archive, citizen IDs, incident reports - agrees
with /lore timeline.

The offset is derived from the real current year, so the in-world calendar
advances day by day and rolls into the next year after the same span of real
time. Earlier real dates map by the same shift, which keeps existing database
rows consistent with each other.

Override with environment variables:
    DRAVIA_CURRENT_YEAR=1985     the in-world year for the real current year
    DRAVIA_FOUNDED_YEAR=1953     founding of the Republic, used by the timeline
"""
import os
from datetime import date, datetime

#: In-world year that corresponds to the real current year.
CURRENT_YEAR = int(os.getenv("DRAVIA_CURRENT_YEAR", "1985"))

#: Year the Republic of Dravia was founded.
FOUNDED_YEAR = int(os.getenv("DRAVIA_FOUNDED_YEAR", "1953"))

#: Long-form name for the current era, used in footers.
ERA = "Present Day"


def year_offset() -> int:
    """Signed number of years between the real and Dravian calendars."""
    return CURRENT_YEAR - datetime.now().year


def _coerce(value):
    """Accept a datetime, date, or ISO-8601 string (as stored in SQLite)."""
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def to_dravian(value):
    """Shift a real date/datetime into the Dravian calendar.

    Returns None for input that cannot be parsed, so callers can fall back
    rather than crash on a legacy or malformed row.
    """
    parsed = _coerce(value)
    if parsed is None:
        return None
    target = parsed.year + year_offset()
    try:
        return parsed.replace(year=target)
    except ValueError:
        # 29 February landing in a non-leap Dravian year.
        return parsed.replace(year=target, day=28)


def dravian_now() -> datetime:
    """The current moment on the Dravian calendar."""
    return to_dravian(datetime.now())


def dravian_today() -> date:
    """Today's Dravian date."""
    return dravian_now().date()


def stamp(value=None, fmt: str = "%d %B %Y, %H:%M") -> str:
    """Format a date for display, on the Dravian calendar.

    `value` may be a datetime, a date, an ISO-8601 string from the database,
    or None (meaning now). Unparseable input is echoed back unchanged so a bad
    row stays visible instead of silently disappearing.
    """
    if value is None:
        value = datetime.now()
    if isinstance(value, str):
        parsed = _coerce(value)
        if parsed is None:
            return value
        value = parsed
    return to_dravian(value).strftime(fmt)


def dravian_timestamp(value=None) -> int:
    """Unix timestamp for a date on the Dravian calendar, for Discord <t:...>.

    Only use this with ABSOLUTE Discord formats (`:D`, `:F`, `:d`). Discord
    computes RELATIVE formats (`:R`, `:t`) against the real current time, so a
    shifted timestamp would render as "41 years ago" instead of "in 30 days".
    This codebase uses `:D` throughout.
    """
    if value is None:
        value = datetime.now()
    shifted = to_dravian(value)
    if shifted is None:
        shifted = datetime.now()
    return int(shifted.timestamp())