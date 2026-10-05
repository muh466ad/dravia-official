"""Dravia State Bot - Input Validation

Command arguments arrive as raw strings from Discord. Every money amount, id,
date and free-text field in the expansion module is passed through these before
it reaches SQL, so a bad value produces a clear message instead of a stack trace
or, worse, a silently mangled record.

All validators raise `ValidationError`, whose message is safe to show a player.
"""
from datetime import date, datetime

from utils.embeds import OVI


class ValidationError(Exception):
    """Invalid input. `str(exc)` is written to be shown to the user."""


def _fail(message: str):
    raise ValidationError(message)


def amount(value, field: str = "Amount", minimum: int = 1, maximum: int | None = None) -> int:
    """A whole positive Ovi amount.

    Rejects floats, negatives and zero so a caller cannot create negative money
    by accident, and enforces an optional ceiling for system limits.
    """
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        _fail(f"{field} must be a whole number of Ovi.")

    if parsed < minimum:
        if minimum == 1:
            _fail(f"{field} must be at least 1 {OVI}.")
        _fail(f"{field} must be at least {minimum:,} {OVI}.")
    if maximum is not None and parsed > maximum:
        _fail(f"{field} cannot exceed {maximum:,} {OVI}.")
    return parsed


def whole_number(value, field: str = "Value", minimum: int | None = None,
                 maximum: int | None = None) -> int:
    """Any integer, for quantities, limits and levels. May be zero or negative."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        _fail(f"{field} must be a whole number.")
    if minimum is not None and parsed < minimum:
        _fail(f"{field} must be at least {minimum:,}.")
    if maximum is not None and parsed > maximum:
        _fail(f"{field} cannot exceed {maximum:,}.")
    return parsed


def record_id(value, field: str = "ID") -> int:
    """A positive database primary key."""
    return whole_number(value, field=field, minimum=1)


def percentage(value, field: str = "Rate", maximum: float = 100.0) -> float:
    """A percentage such as a management fee. Must be 0-100 inclusive."""
    try:
        parsed = float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        _fail(f"{field} must be a percentage, e.g. 2.5")
    if parsed < 0:
        _fail(f"{field} cannot be negative.")
    if parsed > maximum:
        _fail(f"{field} cannot exceed {maximum:g}%.")
    return parsed


def text(value, field: str = "Input", minimum: int = 1, maximum: int = 500) -> str:
    """Free text with the length clamped and surrounding whitespace removed.

    Does not strip user mentions or markdown: players legitimately write `@name`
    and bold text, and Discord renders mentions harmlessly in embeds.
    """
    if value is None:
        _fail(f"{field} is required.")
    cleaned = " ".join(str(value).split())
    if len(cleaned) < minimum:
        if minimum == 1:
            _fail(f"{field} cannot be empty.")
        _fail(f"{field} must be at least {minimum} characters.")
    if len(cleaned) > maximum:
        _fail(f"{field} cannot exceed {maximum} characters (got {len(cleaned)}).")
    return cleaned


def choice(value, allowed, field: str = "Choice") -> str:
    """Restrict a string to a fixed set, matching case-insensitively."""
    options = {str(a).lower(): str(a) for a in allowed}
    key = str(value).strip().lower()
    if key not in options:
        pretty = ", ".join(sorted(options.values()))
        _fail(f"{field} must be one of: {pretty}.")
    return options[key]


def dravian_date(value, field: str = "Date", future_okay: bool = False) -> date:
    """Parse a date in `DD/MM/YYYY` - the format `/apply` already documents."""
    text_value = str(value).strip()
    parsed = None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(text_value, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        _fail(f"{field} must be in **DD/MM/YYYY** format (e.g. 15/03/1998).")
    if not future_okay and parsed > date.today():
        _fail(f"{field} cannot be in the future.")
    return parsed


def discord_id(value, field: str = "User") -> str:
    """A Discord snowflake, stored as text like the rest of the schema."""
    raw = str(value).strip()
    if not raw.isdigit() or not 15 <= len(raw) <= 20:
        _fail(f"{field} is not a valid Discord ID.")
    return raw


def check_funds(balance: int, cost: int, field: str = "Cost") -> None:
    """Guard a debit before it happens, with a message naming the shortfall."""
    if cost <= 0:
        _fail(f"{field} must be positive.")
    if balance < cost:
        short = cost - balance
        _fail(
            f"Insufficient funds: this costs {cost:,} {OVI} but you hold "
            f"{balance:,}. You are {short:,} {OVI} short."
        )


def pagination(page: int, per_page: int = 10, total: int = 0) -> int:
    """Clamp a 1-based page number, returning the number of pages."""
    page = max(1, page)
    pages = max(1, -(-total // per_page)) if total else 1
    return min(page, pages)