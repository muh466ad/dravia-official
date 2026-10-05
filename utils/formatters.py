"""Dravia State Bot - Formatters"""
import discord

from config import COLOR_ACCENT, COLOR_CRIMSON, COLOR_GOLD

OVI = "🪙"


def ovi(amount) -> str:
    """Format an amount as Ovi, e.g. '🪙 1,500'."""
    try:
        return f"{OVI} **{int(amount):,}**"
    except (TypeError, ValueError):
        return f"{OVI} **0**"


def footer(text: str = "Republic of Dravia") -> str:
    """Standard embed footer text."""
    return f"Republic of Dravia | {text}"


def success_embed(title: str, description: str = "") -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=COLOR_ACCENT)
    embed.set_footer(text=footer())
    return embed


def error_embed(title: str, description: str = "") -> discord.Embed:
    embed = discord.Embed(title=f"❌ {title}", description=description, color=COLOR_CRIMSON)
    embed.set_footer(text=footer())
    return embed


def info_embed(title: str, description: str = "") -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=COLOR_GOLD)
    embed.set_footer(text=footer())
    return embed
