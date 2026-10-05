"""Dravia State Bot - Consumer Protection Authority"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.checks import requires_consumer
from utils.logger import audit_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

TRIBUNAL_LIMIT = 5000
RIGHTS = (
    "1️⃣ Right to Satisfactory Quality\n"
    "2️⃣ Right to Fitness for Purpose\n"
    "3️⃣ Right to Match Description"
)
REMEDIES = (
    "• **30-day right to reject** — full refund\n"
    "• **Repair or replacement** — after 30 days\n"
    "• **Price reduction** — if repair/replacement impossible"
)

class Consumer(commands.Cog):
    """Consumer protection commands."""
    
    consumer_group = app_commands.Group(name="consumer", description="Consumer protection commands")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    @consumer_group.command(name="rights", description="View your consumer rights")
    async def consumer_rights(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚖️ Consumer Rights — Three Fundamental Rights",
            description=RIGHTS,
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Remedies", value=REMEDIES, inline=False)
        embed.add_field(
            name="Burden of Proof",
            value="On the **trader** for the first **6 months** after purchase.",
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | Consumer Protection Authority")
        await interaction.response.send_message(embed=embed)

    @consumer_group.command(name="complaint", description="File a consumer complaint")
    @app_commands.describe(trader="The trader you have a dispute with", reason="What went wrong")
    async def consumer_complaint(self, interaction: discord.Interaction, trader: str, reason: str):
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO consumer_complaints (complainant_id, trader_id, reason, filed_at) VALUES (?, ?, ?, ?)",
                (user_id, trader, reason, datetime.now().isoformat()),
            )
            case_id = cursor.lastrowid
            await db.commit()

        audit_log.info("Consumer complaint #%s filed by %s against %s", case_id, user_id, trader)
        embed = discord.Embed(
            title="⚖️ Complaint Filed",
            description=f"Case **#{case_id}** opened against **{trader}**",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Reason", value=reason[:1000], inline=False)
        embed.add_field(name="Status", value="⏳ Under review", inline=True)
        embed.add_field(name="Check Status", value=f"`/consumer status {case_id}`", inline=False)
        embed.set_footer(text="Republic of Dravia | Consumer Protection Authority")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @consumer_group.command(name="status", description="Check a complaint's status")
    @app_commands.describe(case_id="Case number")
    async def consumer_status(self, interaction: discord.Interaction, case_id: int):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM consumer_complaints WHERE id = ?", (case_id,)) as cursor:
                row = await cursor.fetchone()
        if not row:
            await interaction.response.send_message("❌ Case not found.", ephemeral=True)
            return

        embed = discord.Embed(title=f"⚖️ Case #{case_id}", color=COLOR_ACCENT)
        embed.add_field(name="Complainant", value=f"<@{row['complainant_id']}>", inline=True)
        embed.add_field(name="Trader", value=row["trader_id"], inline=True)
        embed.add_field(name="Status", value=row["status"].title(), inline=True)
        embed.add_field(name="Reason", value=(row["reason"] or "")[:1000], inline=False)
        if row["outcome"]:
            embed.add_field(name="Outcome", value=row["outcome"], inline=False)
        embed.set_footer(text=f"Filed {(row['filed_at'] or '')[:10]}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @consumer_group.command(name="refund", description="Request a refund under the 30-day right to reject")
    @app_commands.describe(purchase_id="Purchase/transaction reference", reason="Why the goods are unsatisfactory")
    async def consumer_refund(self, interaction: discord.Interaction, purchase_id: str, reason: str):
        embed = discord.Embed(
            title="↩️ Refund Request Submitted",
            description=f"Purchase **{purchase_id}** — within the **30-day right to reject**, a full refund is owed.",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Reason", value=reason[:1000], inline=False)
        embed.add_field(name="Next Step", value="The trader has 14 days to respond.", inline=False)
        embed.set_footer(text="Republic of Dravia | Consumer Protection Authority")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @consumer_group.command(name="recall", description="Report an unsafe product")
    @app_commands.describe(product="Product name", hazard="Description of the hazard")
    async def consumer_recall(self, interaction: discord.Interaction, product: str, hazard: str):
        audit_log.warning(
            "Unsafe product reported by %s: %s — %s", interaction.user.id, product, hazard
        )
        embed = discord.Embed(
            title="🚨 Unsafe Product Reported",
            description=f"**{product}** — hazard: {hazard[:500]}",
            color=COLOR_CRIMSON,
        )
        embed.add_field(
            name="Precautionary Principle",
            value="The Authority may order an immediate recall pending investigation.",
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | Consumer Protection Authority")
        await interaction.response.send_message(embed=embed)

    @consumer_group.command(name="tribunal", description="File a small claim (under 5,000 Ovi)")
    @app_commands.describe(claim="Description of your claim", amount="Claim amount in Ovi")
    async def consumer_tribunal(self, interaction: discord.Interaction, claim: str, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        if amount > TRIBUNAL_LIMIT:
            await interaction.response.send_message(
                f"❌ The Small Claims Tribunal only hears claims under 🪙 {TRIBUNAL_LIMIT:,}.", ephemeral=True
            )
            return

        audit_log.info("Tribunal claim of %s Ovi by %s", amount, interaction.user.id)
        embed = discord.Embed(
            title="🏛️ Small Claim Filed",
            description=f"Claim of 🪙 **{amount:,}** lodged with the Small Claims Tribunal",
            color=COLOR_GOLD,
        )
        embed.add_field(name="Claim", value=claim[:1000], inline=False)
        embed.add_field(name="Status", value="⏳ Listed for hearing", inline=True)
        embed.set_footer(text="Republic of Dravia | Small Claims Tribunal")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Authority commands ---

    @consumer_group.command(name="investigate", description="Open an investigation (Authority)")
    @app_commands.describe(case_id="Case number")
    @requires_consumer
    async def consumer_investigate(self, interaction: discord.Interaction, case_id: int):
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE consumer_complaints SET status = 'investigating' WHERE id = ?", (case_id,)
            )
            await db.commit()
        audit_log.info("Investigation opened on case #%s by %s", case_id, interaction.user.id)
        await interaction.response.send_message(f"🔍 Case **#{case_id}** — investigation opened.", ephemeral=True)

    @consumer_group.command(name="order", description="Issue a compliance order (Authority)")
    @app_commands.describe(trader="Trader", action="Required action")
    @requires_consumer
    async def consumer_order(self, interaction: discord.Interaction, trader: str, action: str):
        audit_log.warning("Compliance order on %s by %s: %s", trader, interaction.user.id, action)
        embed = discord.Embed(
            title="📋 Compliance Order Issued",
            description=f"**{trader}** is ordered to: {action[:500]}",
            color=COLOR_CRIMSON,
        )
        embed.set_footer(text="Failure to comply = prosecution")
        await interaction.response.send_message(embed=embed)

    @consumer_group.command(name="fine", description="Fine a trader (Authority)")
    @app_commands.describe(trader="Trader", amount="Fine amount", reason="Reason")
    @requires_consumer
    async def consumer_fine(self, interaction: discord.Interaction, trader: str, amount: int, reason: str):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        audit_log.warning("Consumer fine %s Ovi on %s by %s: %s", amount, trader, interaction.user.id, reason)
        embed = discord.Embed(
            title="💸 Fine Issued",
            description=f"**{trader}** fined 🪙 **{amount:,}**\nReason: {reason[:500]}",
            color=COLOR_CRIMSON,
        )
        await interaction.response.send_message(embed=embed)

    @consumer_group.command(name="recall_order", description="Order a product recall (Authority)")
    @app_commands.describe(product="Product", reason="Reason")
    @requires_consumer
    async def consumer_recall_order(self, interaction: discord.Interaction, product: str, reason: str):
        audit_log.warning("RECALL ORDER: %s by %s: %s", product, interaction.user.id, reason)
        embed = discord.Embed(
            title="🚨 RECALL ORDER",
            description=f"**{product}** must be recalled immediately.\nReason: {reason[:500]}",
            color=COLOR_CRIMSON,
        )
        embed.set_footer(text="Strict liability applies to manufacturers")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Consumer(bot))
