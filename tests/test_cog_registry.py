"""The systematic guarantee behind "all 35 cogs work like the others".

Where the other suites test individual systems, this file checks the registry
itself:

* every cog listed in bot.py actually loads (setup() runs, commands register,
  cross-cog name collisions and bad annotations surface here);
* every cog file on disk is registered, and vice versa — no orphans;
* every table the expansion migration creates is used by some cog, so no
  system ships as schema-only;
* the top-level command count stays inside Discord's 100-command limit;
* the /help embed stays inside Discord's 6000-character limit.

Run with:
    python -m pytest tests/test_cog_registry.py -q
"""
import asyncio
import os

import pytest

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "0")

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

import bot as bot_mod  # noqa: E402
import migrate  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COGS_DIR = os.path.join(ROOT, "cogs")


def _fresh_bot_with_cogs():
    """Load every registered cog into an offline Bot.

    Returns (bot, errors). Loading is offline — no login, no gateway — but it
    exercises the real `setup()` path and tree registration, which is where a
    duplicate command name or an uninspectable annotation would blow up.
    """
    async def go():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        errors = {}
        for name in bot_mod.ALL_COGS:
            try:
                await bot.load_extension(name)
            except Exception as exc:  # collected so one failure doesn't hide the rest
                errors[name] = f"{type(exc).__name__}: {exc}"
        return bot, errors
    return asyncio.run(go())


def test_all_registered_cogs_load():
    bot, errors = _fresh_bot_with_cogs()
    assert not errors, f"cogs failed to load: {errors}"
    assert len(bot.extensions) == len(bot_mod.ALL_COGS)


def test_every_cog_file_is_registered():
    """A cog file sitting unregistered would silently never ship."""
    on_disk = {f"cogs.{name[:-3]}" for name in os.listdir(COGS_DIR)
               if name.endswith(".py")}
    registered = set(bot_mod.ALL_COGS)
    assert on_disk == registered, (
        f"unregistered files: {sorted(on_disk - registered)}; "
        f"listed but missing: {sorted(registered - on_disk)}"
    )


def test_registered_cogs_are_grouped():
    """Every cog belongs to exactly one help category."""
    grouped = [cog for cogs in bot_mod.COG_GROUPS.values() for cog in cogs]
    assert sorted(grouped) == sorted(bot_mod.ALL_COGS)
    assert len(grouped) == len(set(grouped)), "a cog appears in two categories"


def test_top_level_command_count_fits_discord_limit():
    """Discord allows 100 top-level chat-input commands; groups keep us under."""
    bot, errors = _fresh_bot_with_cogs()
    assert not errors, f"cogs failed to load: {errors}"
    count = len(bot.tree.get_commands())
    names = [c.name for c in bot.tree.get_commands()]
    assert len(names) == len(set(names)), "duplicate top-level command names"
    assert count <= 100, (
        f"{count} top-level commands registered — Discord rejects registrations over 100"
    )


def test_every_expansion_table_has_an_owning_cog():
    """migration 001 creates 40 tables; a table no cog reads or writes means
    its system shipped as schema only."""
    sources = []
    for name in sorted(os.listdir(COGS_DIR)):
        if name.endswith(".py"):
            sources.append(open(os.path.join(COGS_DIR, name), encoding="utf-8").read())
    joined = "\n".join(sources)
    orphans = [table for table, _ in migrate.NEW_TABLES if table not in joined]
    assert not orphans, f"tables referenced by no cog: {orphans}"


def test_help_embed_stays_within_discord_limits():
    """The category help text is rendered into one embed; over 6000 characters
    Discord rejects the whole message."""
    description = ("Welcome to the Republic of Dravia! Choose a category "
                   "with `/help category:...`")
    total = len("🏛️ Dravia State Bot - Help") + len(description)
    for name, text in bot_mod.HELP_CATEGORIES.items():
        value = text[:1024]  # help_command slices per field
        assert len(value) <= 1024
        total += len(name) + len(value)
    total += len("Utility") + len("`/help` `/status` `/setup`")
    total += len("Date") + len("The Dravian calendar currently reads **1985**.")
    total += len("Republic of Dravia | For the glory of Dravia!")
    assert total <= 6000, f"/help embed would be {total} characters (limit 6000)"
