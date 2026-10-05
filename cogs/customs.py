"""Dravia State Bot - Customs & Trade (De Mercatura Externa Draviae)"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from utils.calendar import stamp
from database import Database
from utils.checks import requires_customs
from utils.logger import tx_log, audit_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Duty rates by goods category (Part 11)
DUTY_RATES = {
    "raw": ("Raw materials", 0.05),
    "processed": ("Processed goods", 0.10),
    "luxury": ("Luxury goods", 0.20),
    "strategic": ("Strategic goods", 0.00),
    "essential": ("Essential goods", 0.02),
}

DE_MINIMIS_FULL = 500     # full exemption under 500 Ovi
DE_MINIMIS_SIMPLIFIED = 2000  # simplified procedure under 2,000 Ovi

class Customs(commands.Cog):
    """Customs & trade commands."""
    
    customs_group = app_commands.Group(name="customs", description="Customs declarations and trade commands")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    async def is_aeo(self, user_id: str) -> bool:
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT 1 FROM aeo_traders WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchone() is not None

    @customs_group.command(name="rates", description="View current duty rates")
    async def customs_rates(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🛃 Dravia Duty Rates", color=COLOR_GOLD)
        for key, (name, rate) in DUTY_RATES.items():
            embed.add_field(name=name, value=f"**{rate * 100:.0f}%**", inline=True)
        embed.add_field(
            name="De Minimis",
            value=f"Under 🪙 {DE_MINIMIS_FULL}: **full exemption**\n"
                  f"🪙 {DE_MINIMIS_FULL:,}–{DE_MINIMIS_SIMPLIFIED:,}: **simplified procedure**",
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | Customs Authority")
        await interaction.response.send_message(embed=embed)

    @customs_group.command(name="import", description="File an import declaration")
    @app_commands.describe(goods="Description of goods", value="Declared value in Ovi", origin="Country of origin")
    @app_commands.choices(category=[app_commands.Choice(name=v[0], value=k) for k, v in DUTY_RATES.items()])
    async def customs_import(
        self, interaction: discord.Interaction, goods: str, value: int, origin: str, category: str = "processed"
    ):
        user_id = str(interaction.user.id)
        if value <= 0:
            await interaction.response.send_message("❌ Value must be positive.", ephemeral=True)
            return

        # Calculate duty
        duty = 0
        procedure = "Standard"
        if value < DE_MINIMIS_FULL:
            procedure = "De minimis — exempt"
        else:
            rate = DUTY_RATES.get(category, DUTY_RATES["processed"])[1]
            if await self.is_aeo(user_id):
                rate *= 0.5  # AEO traders get simplified/reduced treatment
                procedure = "AEO simplified (50% of duty)"
            duty = int(value * rate)

        balance = await self.db.get_balance(user_id)
        if balance < duty:
            await interaction.response.send_message(
                f"❌ Duty owed is 🪙 {duty:,}. You have 🪙 {balance:,}.", ephemeral=True
            )
            return

        if duty > 0:
            await self.db.remove_balance(user_id, duty, "customs_duty", f"Import duty: {goods}")

        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                """INSERT INTO customs_declarations (user_id, declaration_type, goods, value, origin, duty_paid, status, filed_at)
                   VALUES (?, 'import', ?, ?, ?, ?, 'pending', ?)""",
                (user_id, goods, value, origin, duty, datetime.now().isoformat()),
            )
            decl_id = cursor.lastrowid
            await db.commit()

        tx_log.info("Import declaration #%s by %s: goods=%s value=%s duty=%s", decl_id, user_id, goods, value, duty)
        embed = discord.Embed(
            title="🛃 Import Declaration Filed",
            description=f"Declaration **#{decl_id}** — *{goods}* from **{origin}**",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Declared Value", value=f"🪙 **{value:,}**", inline=True)
        embed.add_field(name="Duty Paid", value=f"🪙 **{duty:,}**", inline=True)
        embed.add_field(name="Procedure", value=procedure, inline=True)
        embed.add_field(name="Status", value="⏳ Pending inspection", inline=True)
        embed.add_field(name="Check Status", value=f"`/customs status {decl_id}`", inline=False)
        embed.set_footer(text="Republic of Dravia | Customs Authority")
        await interaction.response.send_message(embed=embed)

    @customs_group.command(name="export", description="File an export declaration")
    @app_commands.describe(goods="Description of goods", value="Declared value in Ovi", destination="Destination country")
    async def customs_export(self, interaction: discord.Interaction, goods: str, value: int, destination: str):
        user_id = str(interaction.user.id)
        if value <= 0:
            await interaction.response.send_message("❌ Value must be positive.", ephemeral=True)
            return

        # Exports: no duty, but declaration required
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                """INSERT INTO customs_declarations (user_id, declaration_type, goods, value, origin, duty_paid, status, filed_at)
                   VALUES (?, 'export', ?, ?, ?, 0, 'approved', ?)""",
                (user_id, goods, value, destination, datetime.now().isoformat()),
            )
            decl_id = cursor.lastrowid
            await db.commit()

        audit_log.info("Export declaration #%s by %s: %s -> %s", decl_id, user_id, goods, destination)
        embed = discord.Embed(
            title="🛃 Export Declaration Filed",
            description=f"Declaration **#{decl_id}** — *{goods}* to **{destination}**",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Declared Value", value=f"🪙 **{value:,}**", inline=True)
        embed.add_field(name="Duty", value="🪙 **0** (exports untaxed)", inline=True)
        embed.add_field(name="Status", value="✅ Approved", inline=True)
        embed.set_footer(text="Republic of Dravia | Customs Authority")
        await interaction.response.send_message(embed=embed)

    @customs_group.command(name="permit", description="Request a trade permit")
    @app_commands.describe(permit_type="Permit type", goods="Goods covered")
    @app_commands.choices(permit_type=[
        app_commands.Choice(name="Import Permit", value="import"),
        app_commands.Choice(name="Export Permit", value="export"),
        app_commands.Choice(name="Transhipment Permit", value="transhipment"),
        app_commands.Choice(name="Strategic Goods Permit", value="strategic"),
    ])
    async def customs_permit(self, interaction: discord.Interaction, permit_type: str, goods: str):
        embed = discord.Embed(
            title="📄 Permit Request Submitted",
            description=f"**{permit_type.title()} Permit** for *{goods}*",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Status", value="⏳ Awaiting Customs Officer review", inline=True)
        embed.set_footer(text="Republic of Dravia | Universal permit requirement applies")
        await interaction.response.send_message(embed=embed)

    @customs_group.command(name="transhipment", description="File a transhipment declaration")
    @app_commands.describe(goods="Goods", origin="Origin", destination="Destination")
    async def customs_transhipment(
        self, interaction: discord.Interaction, goods: str, origin: str, destination: str
    ):
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                """INSERT INTO customs_declarations (user_id, declaration_type, goods, value, origin, duty_paid, status, filed_at)
                   VALUES (?, 'transhipment', ?, 0, ?, 0, 'pending', ?)""",
                (user_id, goods, f"{origin} -> {destination}", datetime.now().isoformat()),
            )
            decl_id = cursor.lastrowid
            await db.commit()

        embed = discord.Embed(
            title="🛃 Transhipment Filed",
            description=f"Declaration **#{decl_id}** — *{goods}*\n{origin} → {destination}",
            color=COLOR_ACCENT,
        )
        embed.set_footer(text="Republic of Dravia | Customs Authority")
        await interaction.response.send_message(embed=embed)

    @customs_group.command(name="status", description="Check a declaration's status")
    @app_commands.describe(declaration_id="Declaration number")
    async def customs_status(self, interaction: discord.Interaction, declaration_id: int):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM customs_declarations WHERE id = ?", (declaration_id,)
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message("❌ Declaration not found.", ephemeral=True)
            return

        status_emoji = {"pending": "⏳", "approved": "✅", "seized": "🚫", "rejected": "❌"}.get(row["status"], "•")
        embed = discord.Embed(title=f"🛃 Declaration #{declaration_id}", color=COLOR_ACCENT)
        embed.add_field(name="Type", value=row["declaration_type"].title(), inline=True)
        embed.add_field(name="Goods", value=row["goods"], inline=True)
        embed.add_field(name="Value", value=f"🪙 **{row['value']:,}**", inline=True)
        embed.add_field(name="Origin/Destination", value=row["origin"], inline=True)
        embed.add_field(name="Duty Paid", value=f"🪙 **{row['duty_paid']:,}**", inline=True)
        embed.add_field(name="Status", value=f"{status_emoji} {row['status'].title()}", inline=True)
        embed.set_footer(text=f"Filed {(row['filed_at'] or '')[:10]}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Customs Officer commands ---

    @customs_group.command(name="inspect", description="Inspect a shipment (Customs Officer)")
    @app_commands.describe(declaration_id="Declaration number")
    @requires_customs
    async def customs_inspect(self, interaction: discord.Interaction, declaration_id: int):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM customs_declarations WHERE id = ?", (declaration_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            await interaction.response.send_message("❌ Declaration not found.", ephemeral=True)
            return
        audit_log.info("Inspection of declaration #%s by %s", declaration_id, interaction.user.id)
        embed = discord.Embed(title=f"🔍 Inspection: Declaration #{declaration_id}", color=COLOR_ACCENT)
        embed.add_field(name="Goods", value=row["goods"], inline=True)
        embed.add_field(name="Declared Value", value=f"🪙 **{row['value']:,}**", inline=True)
        embed.add_field(name="Risk Level", value="Standard screening", inline=True)
        embed.set_footer(text="Approve with /customs approve or seize with /customs seize")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @customs_group.command(name="approve", description="Approve a declaration (Customs Officer)")
    @app_commands.describe(declaration_id="Declaration number")
    @requires_customs
    async def customs_approve(self, interaction: discord.Interaction, declaration_id: int):
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE customs_declarations SET status = 'approved' WHERE id = ?", (declaration_id,)
            )
            await db.commit()
        audit_log.info("Declaration #%s approved by %s", declaration_id, interaction.user.id)
        await interaction.response.send_message(f"✅ Declaration **#{declaration_id}** approved.", ephemeral=True)

    @customs_group.command(name="seize", description="Seize goods (Customs Officer)")
    @app_commands.describe(declaration_id="Declaration number", reason="Reason for seizure")
    @requires_customs
    async def customs_seize(self, interaction: discord.Interaction, declaration_id: int, reason: str):
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE customs_declarations SET status = 'seized' WHERE id = ?", (declaration_id,)
            )
            await db.commit()
        audit_log.warning(
            "SEIZURE: declaration #%s by %s reason=%s", declaration_id, interaction.user.id, reason
        )
        embed = discord.Embed(
            title="🚫 Goods Seized",
            description=f"Declaration **#{declaration_id}** seized.\nReason: {reason}",
            color=COLOR_CRIMSON,
        )
        embed.set_footer(text="Republic of Dravia | Seizure and forfeiture proceedings initiated")
        await interaction.response.send_message(embed=embed)

    @customs_group.command(name="audit", description="Post-clearance audit (Customs Officer)")
    @app_commands.describe(user="Trader to audit")
    @requires_customs
    async def customs_audit(self, interaction: discord.Interaction, user: discord.User):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT COUNT(*) as n, COALESCE(SUM(value),0) as v FROM customs_declarations WHERE user_id = ?",
                (str(user.id),),
            ) as cursor:
                row = await cursor.fetchone()
        audit_log.info("Post-clearance audit on %s by %s", user.id, interaction.user.id)
        embed = discord.Embed(title=f"🔎 Post-Clearance Audit: {user.display_name}", color=COLOR_ACCENT)
        embed.add_field(name="Declarations", value=f"**{row['n']}**", inline=True)
        embed.add_field(name="Total Declared Value", value=f"🪙 **{row['v']:,}**", inline=True)
        embed.add_field(name="Retention Period", value="**3 years**", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @customs_group.command(name="aeo_apply", description="Apply for Authorised Economic Operator status")
    async def customs_aeo_apply(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        if await self.is_aeo(user_id):
            await interaction.response.send_message("✅ You already hold AEO status.", ephemeral=True)
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT OR IGNORE INTO aeo_traders (user_id, approved_at) VALUES (?, ?)",
                (user_id, datetime.now().isoformat()),
            )
            await db.commit()
        audit_log.info("AEO status granted to %s", user_id)
        embed = discord.Embed(
            title="🏅 AEO Status Granted",
            description="Your cargo receives **mutual recognition**, simplified declarations and 50% duty treatment on inspections.",
            color=COLOR_GOLD,
        )
        embed.set_footer(text="Republic of Dravia | AEO Programme")
        await interaction.response.send_message(embed=embed)

    @customs_group.command(name="aeo_list", description="List all AEO traders")
    async def customs_aeo_list(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT user_id, approved_at FROM aeo_traders LIMIT 15") as cursor:
                rows = await cursor.fetchall()
        embed = discord.Embed(title="🏅 AEO Traders", color=COLOR_GOLD)
        if not rows:
            embed.description = "No AEO traders yet. Apply with `/customs aeo_apply`."
        else:
            for uid, approved in rows:
                embed.add_field(name=f"<@{uid}>", value=f"Since {stamp(approved, '%d %b %Y')}", inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Customs(bot))
