"""Dravia State Bot - Input Validators"""


def validate_amount(amount: int, minimum: int = 1, maximum: int = 1_000_000_000) -> str:
    """Return an error message if the amount is invalid, else None."""
    if amount is None:
        return "Amount is required."
    if not isinstance(amount, int):
        return "Amount must be a whole number."
    if amount < minimum:
        return f"Amount must be at least {minimum:,}."
    if amount > maximum:
        return f"Amount must not exceed {maximum:,}."
    return None


def validate_name(name: str, max_length: int = 64) -> str:
    """Validate a name/string field."""
    if not name or not name.strip():
        return "Name cannot be empty."
    if len(name) > max_length:
        return f"Name must be {max_length} characters or fewer."
    return None


def validate_percent(value: float) -> str:
    if value is None or value < 0 or value > 100:
        return "Value must be between 0 and 100."
    return None


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
