"""Dravia State Bot - Shared Cog Base

Gives every expansion cog the same plumbing so individual systems stay short:
a wired `Database`, money helpers that check funds before debiting, a cooldown
decorator backed by the `expires_at` column, and consistent error replies.

Money rule: `debit` refuses to take a balance negative and returns False rather
than raising, so a command can bail out early with a user-facing message.
"""
import functools
import inspect
from datetime import date, datetime

import discord
from discord import app_commands
from discord.ext import commands

from database import Database
from utils.embeds import OVI, DraviaEmbed, error, success, warning
from utils.logger import audit_log, bot_log
from utils.validation import ValidationError

#: Command group -> cooldown seconds, per system F2 of the expansion spec.
COOLDOWNS = {
    "economy": 3,
    "police": 5,
    "business": 10,
    "market": 30,
    "gambling": 60,
}


class DraviaCog(commands.Cog):
    """Base for expansion cogs."""

    #: Name of the APP_COMMANDS group this cog hangs off, used by `cooldown`.
    group_name: str = "economy"

    def __init__(self, bot, db_path: str | None = None):
        self.bot = bot
        # Read `database.DATABASE_PATH` at construction rather than snapshotting
        # our own copy at import time. Re-resolving getenv here would add a
        # fourth divergent copy of the path - the same class of bug that split
        # the bot across two database files early in development.
        import database
        self.db = Database(db_path or database.DATABASE_PATH)

    # ------------------------------------------------------------- money
    async def balance_of(self, user_id: str) -> int:
        return await self.db.get_balance(str(user_id))

    async def credit(self, user_id: str, amount: int, tx_type: str, description: str = "") -> bool:
        await self.db.create_user(str(user_id))
        await self.db.add_balance(str(user_id), amount, tx_type, description)
        audit_log.info("credit %s -> %s amount=%s reason=%s", user_id, tx_type, amount, description)
        return True

    async def can_afford(self, user_id: str, cost: int) -> bool:
        return await self.balance_of(user_id) >= cost

    async def debit(self, user_id: str, amount: int, tx_type: str, description: str = "") -> bool:
        """Remove `amount` if the user can afford it. Returns False otherwise."""
        if amount <= 0:
            return False
        if not await self.can_afford(user_id, amount):
            return False
        await self.db.create_user(str(user_id))
        await self.db.remove_balance(str(user_id), amount, tx_type, description)
        audit_log.info("debit %s -> %s amount=%s reason=%s", user_id, tx_type, amount, description)
        return True

    async def transfer(self, from_id: str, to_id: str, amount: int, description: str = "") -> bool:
        if amount <= 0 or not await self.can_afford(from_id, amount):
            return False
        await self.db.transfer(str(from_id), str(to_id), amount, description)
        audit_log.info("transfer %s -> %s amount=%s", from_id, to_id, amount)
        return True

    # --------------------------------------------------------- responses
    @staticmethod
    async def reply(interaction, embed, *, private: bool = True):
        await interaction.response.send_message(embed=embed, ephemeral=private)

    @staticmethod
    async def fail(interaction, message: str):
        await interaction.response.send_message(
            embed=error("Not permitted" if "permission" in message.lower() else "Unable to complete", message),
            ephemeral=True,
        )

    # ------------------------------------------------------ cooldowns (F2)
    def cooldown(self, command: str):
        """Per-user cooldown in seconds, taken from `COOLDOWNS[self.group_name]`.

        Silently no-ops when the migration has not been applied, so a missing
        migration degrades the feature instead of breaking the command.
        """
        seconds = COOLDOWNS.get(self.group_name, 3)

        def decorator(func):
            @functools.wraps(func)
            async def wrapper(self, interaction, *args, **kwargs):
                if getattr(interaction.client, "is_admin", None) and self._is_admin(interaction):
                    return await func(self, interaction, *args, **kwargs)
                remaining = await self.db.cooldown_remaining(str(interaction.user.id), command)
                if remaining > 0:
                    await interaction.response.send_message(
                        embed=warning("Slow down", f"Try again in **{remaining:.0f}s**."),
                        ephemeral=True,
                    )
                    return
                await self.db.set_expiring_cooldown(str(interaction.user.id), command, seconds)
                return await func(self, interaction, *args, **kwargs)
            return wrapper
        return decorator

    @staticmethod
    def _is_admin(interaction) -> bool:
        try:
            return bool(interaction.user.guild_permissions.administrator)
        except Exception:
            return False


# --------------------------------------------------------------- helpers
def handles_validation(func):
    """Turn a validator's `ValidationError` into a user-facing error embed.

    `utils.validation` raises with a message that is safe to show a player, so
    a rejected input should reach them as an embed rather than escaping the
    callback as a stack trace. Apply directly above the command callback:

        @GROUP.command(name="claim", ...)
        @handles_validation
        async def claim(self, interaction, value): ...

    `__signature__` is pinned to the original so app_commands still sees the
    annotated parameters it needs to register the slash command.
    """
    @functools.wraps(func)
    async def wrapper(self, interaction, *args, **kwargs):
        try:
            return await func(self, interaction, *args, **kwargs)
        except ValidationError as exc:
            await self.fail(interaction, str(exc))
    wrapper.__signature__ = inspect.signature(func)
    return wrapper


def log_action(domain: str, action: str, actor: str, **fields):
    """Uniform audit line for anything that changes money or state."""
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    audit_log.info("[%s] %s by %s %s", domain, action, actor, extra)


def today() -> str:
    return date.today().isoformat()


def now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def ovi(value: int) -> str:
    return f"{OVI} **{value:,}**"


__all__ = [
    "DraviaCog", "COOLDOWNS", "app_commands", "discord",
    "DraviaEmbed", "success", "error", "warning", "ovi",
    "ValidationError", "handles_validation", "log_action", "today", "now",
    "bot_log", "audit_log",
]