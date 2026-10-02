"""Dravia State Bot - Main Entry Point"""
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import DISCORD_TOKEN, DEV_GUILD_ID, COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import init_db, Database
from utils.logger import bot_log, error_log, log_error
from scheduler import DraviaScheduler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DraviaBot")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
bot.db = Database()
bot.started_at = datetime.now(timezone.utc)

# Color scheme from Dravian flag
COLORS = {
    "crimson": COLOR_CRIMSON,
    "gold": COLOR_GOLD,
    "black": 0x1A1A1A,
    "accent": COLOR_ACCENT
}

# All cogs, grouped for the help command
COG_GROUPS = {
    "💰 Economy": ["cogs.economy", "cogs.banking", "cogs.taxes"],
    "🏛️ Government": ["cogs.citizenship", "cogs.civil_service", "cogs.curia", "cogs.grants", "cogs.news", "cogs.lore", "cogs.admin"],
    "👮 Police": ["cogs.police", "cogs.police_academy"],
    "🏢 Commerce": ["cogs.business", "cogs.mining", "cogs.stock_market", "cogs.customs", "cogs.consumer_protection", "cogs.events"],
    "🎮 Society": ["cogs.gambling", "cogs.housing"],
}

HELP_CATEGORIES = {
    "💰 Economy": (
        "`/balance` `/pay` `/daily` `/weekly` `/leaderboard` `/economy`\n"
        "`/bank balance|deposit|withdraw|loan|repay`\n"
        "`/tax check|declare|pay|history|wealth|estimate`"
    ),
    "🏛️ Government": (
        "`/apply` `/myid` `/lookup` `/citizens` `/setrank`\n"
        "`/civilservice apply|status|salary|list|approve|promote|dismiss`\n"
        "`/curia propose|vote|status|debate|summon|register`  `/audit police|economy|business|government|citizen`\n"
        "`/grant` `/grants` `/news publish|list|latest` `/gazette announce|budget|production`\n"
        "`/lore flag|characters|history|constitution|comic`  `/setup` `/admin pay|set_balance|log|roles`"
    ),
    "👮 Police": (
        "`/police join|record|wanted|duty_start|duty_end|status|miranda|cuff|search|jail|release`\n"
        "`/police warrant_issue|warrant_serve|warrant_list|bolo_create|bolo_list|report|radio`\n"
        "`/arrest` `/pay_fine`\n"
        "`/ia complaint|investigate|findings|penalty|register`\n"
        "`/ipoc review|adopt_or_explain|investigate|report|mediation`\n"
        "`/academy apply|exam|train|test|status|graduate|oath`"
    ),
    "🏢 Commerce": (
        "`/business register|list|info|renew|close|hire|fire|employees|report`\n"
        "`/facility build|upgrade|status`  `/produce` `/inventory`\n"
        "`/mine claim|build|produce|refine|status|safety|bond|close`\n"
        "`/stock list|buy|sell|portfolio`\n"
        "`/customs import|export|permit|status|rates|inspect|approve|seize|audit`\n"
        "`/consumer rights|complaint|status|refund|tribunal|fine`\n"
        "`/event propose|list|register|sponsor|vendor|calendar`"
    ),
    "🎮 Society": (
        "`/casino slots|blackjack|roulette|dice|crash|limits|self_exclude|stats`\n"
        "`/lottery buy|draw|jackpot`\n"
        "`/house apply|invite|remove|renew|cancel|info`"
    ),
}

ALL_COGS = [cog for group in COG_GROUPS.values() for cog in group]


@bot.event
async def on_ready():
    """Bot startup event."""
    logger.info(f"🤖 Dravia State Bot logged in as {bot.user}")
    logger.info(f"📊 Bot ID: {bot.user.id}")
    bot_log.info("Bot ready as %s", bot.user)
    logger.info("✅ Bot fully initialized and ready!")


async def load_cogs():
    """Load all bot cogs."""
    for cog in ALL_COGS:
        try:
            await bot.load_extension(cog)
            logger.info(f"✅ Loaded cog: {cog}")
        except Exception as e:
            log_error(f"Failed to load {cog}", e)
            logger.error(f"❌ Failed to load {cog}: {e}")


async def sync_commands():
    """Sync slash commands to Discord."""
    if DEV_GUILD_ID:
        guild = bot.get_guild(DEV_GUILD_ID)
        if guild:
            await bot.tree.sync(guild=guild)
            logger.info(f"✅ Synced commands to dev guild: {guild.name}")
            return
    await bot.tree.sync()
    logger.info("✅ Synced commands globally")


@bot.tree.command(name="help", description="Show help information by category")
@app_commands.describe(category="Help category")
@app_commands.choices(category=[app_commands.Choice(name=c, value=c) for c in HELP_CATEGORIES])
async def help_command(interaction: discord.Interaction, category: str = None):
    """Show categorized help menu."""
    if category:
        embed = discord.Embed(
            title=f"🏛️ Dravia State Bot — {category}",
            description=HELP_CATEGORIES[category],
            color=COLORS["accent"]
        )
    else:
        embed = discord.Embed(
            title="🏛️ Dravia State Bot - Help",
            description="Welcome to the Republic of Dravia! Choose a category with `/help category:...`",
            color=COLORS["accent"]
        )
        for name, commands_text in HELP_CATEGORIES.items():
            embed.add_field(name=name, value=commands_text[:1024], inline=False)

    embed.add_field(name="Utility", value="`/help` `/status` `/setup`", inline=False)
    embed.set_footer(text="Republic of Dravia | For the glory of Dravia!")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="status", description="Show bot status")
async def status_command(interaction: discord.Interaction):
    """Show bot status and system health."""
    try:
        stats = await bot.db.get_economy_stats()
    except Exception:
        stats = {"total_users": 0, "total_money": 0, "avg_balance": 0}

    uptime = datetime.now(timezone.utc) - bot.started_at
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    loaded = sum(1 for cog in ALL_COGS if cog in bot.extensions)
    scheduler_jobs = len(bot.scheduler.scheduler.get_jobs()) if getattr(bot, "scheduler", None) else 0

    embed = discord.Embed(title="🤖 Dravia Bot Status", color=COLORS["accent"])
    embed.add_field(name="Total Citizens", value=f"{stats['total_users'] or 0:,}", inline=True)
    embed.add_field(name="Total Money Supply", value=f"🪙 {stats['total_money'] or 0:,}", inline=True)
    embed.add_field(name="Average Balance", value=f"🪙 {stats['avg_balance'] or 0:.0f}", inline=True)
    embed.add_field(name="Uptime", value=f"{hours}h {minutes}m {seconds}s", inline=True)
    embed.add_field(name="Database", value="✅ Connected", inline=True)
    embed.add_field(name="Cogs Loaded", value=f"{loaded}/{len(ALL_COGS)}", inline=True)
    embed.add_field(name="Scheduled Jobs", value=f"{scheduler_jobs}", inline=True)
    embed.add_field(name="Guilds", value=f"{len(bot.guilds)}", inline=True)
    embed.add_field(name="Latency", value=f"{bot.latency * 1000:.0f}ms", inline=True)
    embed.set_footer(text="Republic of Dravia | System Health")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# Error handler
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handle command errors."""
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ Command on cooldown. Try again in {error.retry_after:.0f} seconds.",
            ephemeral=True
        )
    elif isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(
            f"⛔ {str(error) or 'You do not have permission to use this command.'}",
            ephemeral=True
        )
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ You lack the required permissions.", ephemeral=True)
    else:
        log_error(f"Command error in {interaction.command.name if interaction.command else 'unknown'}", error)
        logger.error(f"Command error: {error}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "❌ An error occurred. Please try again later.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ An error occurred. Please try again later.", ephemeral=True
                )
        except Exception:
            pass


async def main():
    """Run the bot with proper setup/teardown."""
    async with bot:
        await init_db()
        bot_log.info("Database ready")
        await load_cogs()
        await sync_commands()
        bot.scheduler = DraviaScheduler(bot)
        bot.scheduler.start()
        try:
            await bot.start(DISCORD_TOKEN)
        finally:
            bot.scheduler.shutdown()


# Run bot
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
