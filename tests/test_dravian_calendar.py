"""Tests for the Dravian in-world calendar and /lore timeline.

Run with:
    python -m pytest tests/ -q
"""
import os
import re
from datetime import date, datetime, timedelta

import pytest

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "0")

from utils.calendar import (  # noqa: E402
    CURRENT_YEAR,
    FOUNDED_YEAR,
    dravian_now,
    dravian_timestamp,
    dravian_today,
    stamp,
    to_dravian,
    year_offset,
)
from cogs.lore import TIMELINE, HISTORY  # noqa: E402


# ------------------------------------------------------------------ mapping
def test_today_is_in_the_current_dravian_year():
    assert dravian_today().year == CURRENT_YEAR
    assert dravian_now().year == CURRENT_YEAR


def test_offset_is_signed_year_difference():
    assert year_offset() == CURRENT_YEAR - datetime.now().year


def test_month_and_day_are_preserved():
    """Only the year moves; a shift that changed the day would silently move
    every scheduled deadline."""
    real = datetime(2026, 3, 14)
    assert to_dravian(real).month == 3
    assert to_dravian(real).day == 14


def test_earlier_dates_shift_by_the_same_offset():
    a = to_dravian(datetime(2020, 6, 1))
    b = to_dravian(datetime(2026, 6, 1))
    assert (b.year - a.year) == 6


def test_mapping_is_consistent_for_dates_several_years_apart():
    years = [to_dravian(datetime(2020 + i, 6, 15)).year for i in range(10)]
    assert years == sorted(years)
    assert years[-1] - years[0] == 9


# ------------------------------------------------------------- leap years
def test_feb_29_falls_back_to_feb_28_in_a_non_leap_dravian_year():
    target = to_dravian(datetime(2028, 2, 29))       # 2028 is a leap year
    assert (target.month, target.day) == (2, 28)
    assert target.year == 2028 + year_offset()


def test_leap_day_survives_when_the_target_year_is_also_a_leap_year(monkeypatch):
    monkeypatch.setattr("utils.calendar.year_offset", lambda: -4)
    # 2028 -> 2024, both leap years, so the 29th must be kept.
    assert to_dravian(datetime(2028, 2, 29)).day == 29


# ------------------------------------------------------------------ stamp
def test_stamp_accepts_an_iso_string_from_sqlite():
    out = stamp("2026-10-03T12:34:56", "%d %B %Y")
    assert out == "03 October " + str(CURRENT_YEAR)


def test_stamp_defaults_to_now():
    assert str(CURRENT_YEAR) in stamp(None)


def test_stamp_echoes_unparseable_input_instead_of_crashing():
    """A malformed legacy row must stay visible, not raise inside a command."""
    assert stamp("not-a-date", "%d %B %Y") == "not-a-date"
    assert stamp("", "%d %B %Y") == ""


def test_stamp_handles_none_values_from_optional_columns():
    """Several tables have nullable date columns; a None must mean "now",
    not a crash."""
    expected = to_dravian(datetime.now()).strftime("%d %B %Y")
    assert stamp(None, "%d %B %Y") == expected


def test_stamp_honours_a_custom_format():
    assert stamp(datetime(2026, 1, 2), "%d/%m/%Y") == f"02/01/{CURRENT_YEAR}"


# ------------------------------------------------------------- timestamps
def test_dravian_timestamp_round_trips_to_the_in_world_date():
    real = datetime.now() + timedelta(days=30)
    got = datetime.fromtimestamp(dravian_timestamp(real)).date()
    assert got == to_dravian(real).date()


def test_dravian_timestamp_defaults_to_now():
    assert datetime.fromtimestamp(dravian_timestamp()).year == CURRENT_YEAR


# --------------------------------------------------------------- timeline
def test_timeline_is_chronological():
    years = [y for y, _, _ in TIMELINE]
    assert years == sorted(years), "TIMELINE must run oldest first"


def test_timeline_stays_inside_the_declared_span():
    for year, title, _ in TIMELINE:
        assert FOUNDED_YEAR <= year <= CURRENT_YEAR, f"{year} ({title}) outside span"


def test_timeline_starts_at_the_founding_year():
    assert TIMELINE[0][0] == FOUNDED_YEAR


def test_timeline_reaches_the_present_year():
    assert TIMELINE[-1][0] == CURRENT_YEAR


def test_exactly_one_event_is_marked_present():
    """The embed adds a 'present' marker to every field matching CURRENT_YEAR,
    so duplicates would mark several entries."""
    assert sum(1 for y, _, _ in TIMELINE if y == CURRENT_YEAR) == 1


def test_timeline_fits_in_one_discord_embed():
    # Discord allows 25 fields and 6000 characters of description.
    assert len(TIMELINE) <= 25


def test_every_event_has_a_title_and_description():
    for year, title, description in TIMELINE:
        assert title.strip(), f"{year} has no title"
        assert description.strip(), f"{year} has no description"


def test_history_points_at_the_timeline():
    assert "/lore timeline" in HISTORY


# ------------------------------------------------------ integration guards
def _cog_sources():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cogs = os.path.join(root, "cogs")
    for f in sorted(os.listdir(cogs)):
        if f.endswith(".py"):
            yield os.path.join(cogs, f)


def test_no_cog_renders_a_raw_iso_date_slice():
    """`row['published_at'][:10]` would print a real-world date next to
    in-world ones."""
    offenders = []
    for path in _cog_sources():
        src = open(path, encoding="utf-8").read()
        for match in re.finditer(r'add_field\([^)]*\[:(?:10|16)\]', src):
            offenders.append(f"{os.path.basename(path)}: {match.group(0)[:60]}")
    assert not offenders, f"real-world dates still displayed: {offenders}"


def test_no_cog_uses_a_relative_discord_timestamp():
    """`:R` and `:t` are computed against real time, so a shifted timestamp
    would render as '41 years ago'."""
    offenders = []
    for path in _cog_sources():
        src = open(path, encoding="utf-8").read()
        for match in re.finditer(r"<t:[^:]*:([A-Za-z])>", src):
            if match.group(1) in {"R", "t"}:
                offenders.append(f"{os.path.basename(path)}: {match.group(0)}")
    assert not offenders, f"relative timestamps break under a year shift: {offenders}"