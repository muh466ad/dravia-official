"""Dravia State Bot - Shared Embed Builders

Every command in the expansion module returns one of these so replies stay
visually consistent and never crash on Discord's hard limits.

Discord enforces these and will reject the whole message otherwise:
    title 256 | description 4096 | field name 256 | field value 1024
    footer 2048 | 25 fields | 6000 characters total

`DraviaEmbed` truncates each of those defensively, because a long player-supplied
name (a business title, an incident report) must not turn into an HTTP 400.
"""
import discord

from config import COLOR_ACCENT, COLOR_BLACK, COLOR_CRIMSON, COLOR_GOLD

#: Currency symbol used across the economy.
OVI = "🪙"

FOOTER = "Republic of Dravia"

# Discord hard limits
MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_FIELD_NAME = 256
MAX_FIELD_VALUE = 1024
MAX_FOOTER = 2048
MAX_FIELDS = 25
MAX_TOTAL = 6000

#: Characters already spent by the envelope, counted against MAX_TOTAL.
_ENVELOPE_COST = 20


def _clean(value, limit: int, fallback: str = "…") -> str:
    """Trim to `limit` characters, never returning an empty string."""
    if value is None:
        return fallback
    text = str(value)
    if not text.strip():
        return fallback
    if len(text) <= limit:
        return text
    if limit <= len(fallback):
        return text[:limit]
    return text[: limit - len(fallback)].rstrip() + fallback


class DraviaEmbed(discord.Embed):
    """Embed preloaded with Dravian colours and Discord-limit clamping."""

    def __init__(self, title: str | None = None,
                 description: str | None = None,
                 color: int = COLOR_GOLD, **kwargs):
        super().__init__(
            title=_clean(title, MAX_TITLE) if title else None,
            description=_clean(description, MAX_DESCRIPTION) if description else None,
            color=color,
            **kwargs,
        )
        self.set_footer(text=FOOTER)

    def add_field(self, name: str, value: str, inline: bool = False):  # noqa: D102
        if len(self.fields) >= MAX_FIELDS:
            return self
        name = _clean(name, MAX_FIELD_NAME)
        value = _clean(value, MAX_FIELD_VALUE)
        # Keep room for the field envelope so the 6000-char cap is not breached.
        if self._spent() + len(name) + len(value) + _ENVELOPE_COST > MAX_TOTAL:
            return self
        super().add_field(name=name, value=value, inline=inline)
        return self

    def set_footer(self, text: str = FOOTER, **kwargs):  # noqa: D102
        super().set_footer(text=_clean(text, MAX_FOOTER), **kwargs)
        return self

    def _spent(self) -> int:
        total = len(self.title or "") + len(self.description or "")
        for f in self.fields:
            total += len(f.name or "") + len(f.value or "")
        footer = self.footer.text if self.footer else ""
        return total + len(footer)


# ------------------------------------------------------------ constructors
def success(title: str, description: str | None = None) -> DraviaEmbed:
    return DraviaEmbed(title=title, description=description, color=COLOR_ACCENT)


def error(title: str = "Error", description: str | None = None) -> DraviaEmbed:
    return DraviaEmbed(title=f"❌ {title}", description=description, color=COLOR_CRIMSON)


def warning(title: str, description: str | None = None) -> DraviaEmbed:
    return DraviaEmbed(title=f"⚠️ {title}", description=description, color=COLOR_GOLD)


def info(title: str, description: str | None = None) -> DraviaEmbed:
    return DraviaEmbed(title=title, description=description, color=COLOR_BLACK)


def official(title: str, description: str | None = None) -> DraviaEmbed:
    """State-published material: Gazette, decrees, official notices."""
    return DraviaEmbed(title=title, description=description, color=COLOR_CRIMSON)


def money_line(amount: int, label: str = "Amount") -> str:
    """Format an Ovi amount, e.g. `1,250 Ovi 🪙`."""
    return f"{label}: {OVI} **{amount:,}**"


def balance_fields(balance: int, change: int | None = None) -> list[tuple[str, str]]:
    """Standard pair of balance fields used by every money-moving command."""
    fields = [("Balance", f"{OVI} **{balance:,}**")]
    if change is not None:
        sign = "+" if change >= 0 else "-"
        fields.append(("Change", f"{OVI} **{sign}{abs(change):,}**"))
    return fields