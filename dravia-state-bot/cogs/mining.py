"""Dravia State Bot - Mining System (De Fodinis Draviae)"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import os
import aiosqlite
import random

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.logger import tx_log, audit_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

CONCESSIONS = {
    "exploration": {"name": "Exploration Permit", "fee": 1000, "annual": 500, "years": 3},
    "mining": {"name": "Mining Lease", "fee": 5000, "annual": 2500, "years": 25},
    "quarry": {"name": "Quarry Permit", "fee": 2500, "annual": 1000, "years": 10},
    "artisanal": {"name": "Artisanal Claim", "fee": 200, "annual": 100, "years": 1},
}

TIERS = {
    1: {"name": "I — Artisanal Claim", "cost": 1000, "points": 10, "bond": 500},
    2: {"name": "II — Small Mine", "cost": 3000, "points": 30, "bond": 1500},
    3: {"name": "III — Medium Mine", "cost": 7500, "points": 75, "bond": 5000},
    4: {"name": "IV — Large Mine", "cost": 15000, "points": 150, "bond": 15000},
    5: {"name": "V — Industrial Complex", "cost": 30000, "points": 300, "bond": 30000},
}

# Mineral point values and royalty rates (Part 6)
MINERALS = {
    "Coal": {"points": 1, "royalty": 0.03},
    "Stone": {"points": 1, "royalty": 0.02},
    "Clay": {"points": 1, "royalty": 0.02},
    "Sand": {"points": 1, "royalty": 0.02},
    "Iron Ore": {"points": 2, "royalty": 0.05},
    "Copper Ore": {"points": 2, "royalty": 0.05},
    "Tin": {"points": 2, "royalty": 0.05},
    "Lead": {"points": 2, "royalty": 0.05},
    "Silver": {"points": 3, "royalty": 0.06},
    "Gold": {"points": 5, "royalty": 0.07},
    "Platinum": {"points": 6, "royalty": 0.07},
    "Gems": {"points": 8, "royalty": 0.10},
}

# Refining: raw -> refined with Ovi value add
REFINING = {
    "Iron Ore": ("Iron Ingot", 10),
    "Copper Ore": ("Copper Ingot", 12),
    "Coal": ("Coke", 3),
    "Gold": ("Gold Bar", 30),
    "Stone": ("Cut Stone", 5),
}

class Mining(commands.Cog):
    """Mining commands for Dravia."""
    
    mine_group = app_commands.Group(name="mine", description="Mining concession and extraction commands")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    async def get_concession(self, user_id: str):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM mining_concessions WHERE owner_id = ? AND is_active = 1", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    @mine_group.command(name="claim", description="Claim a mining concession")
    @app_commands.describe(concession_type="Type of concession", location="Claim location")
    @app_commands.choices(concession_type=[
            app_commands.Choice(name="Exploration Permit (🪙1,000 + 500/yr, 3 yrs)", value="exploration"),
            app_commands.Choice(name="Mining Lease (🪙5,000 + 2,500/yr, 25 yrs)", value="mining"),
            app_commands.Choice(name="Quarry Permit (🪙2,500 + 1,000/yr, 10 yrs)", value="quarry"),
            app_commands.Choice(name="Artisanal Claim (🪙200 + 100/yr, 1 yr)", value="artisanal"),
        ])
    async def mine_claim(self, interaction: discord.Interaction, concession_type: str, location: str):
        user_id = str(interaction.user.id)
        if await self.get_concession(user_id):
            await interaction.response.send_message("⚠️ You already hold an active concession.", ephemeral=True)
            return

        concession = CONCESSIONS[concession_type]
        balance = await self.db.get_balance(user_id)
        if balance < concession["fee"]:
            await interaction.response.send_message(
                f"❌ Fee is 🪙 {concession['fee']:,}. You have 🪙 {balance:,}.", ephemeral=True
            )
            return

        await self.db.remove_balance(user_id, concession["fee"], "concession", f"{concession['name']} fee")
        now = datetime.now()
        expires = now + timedelta(days=365 * concession["years"])

        async with await self.db.get_connection() as db:
            await db.execute(
                """INSERT INTO mining_concessions (company_id, owner_id, concession_type, location, tier,
                   daily_points, royalty_rate, rehabilitation_bond, minerals, granted_at, expires_at, is_active)
                   VALUES (NULL, ?, ?, ?, 0, 0, 0.0, 0, '', ?, ?, 1)""",
                (user_id, concession_type, location, now.isoformat(), expires.isoformat()),
            )
            await db.commit()

        tx_log.info("Concession claimed: %s by %s at %s", concession_type, user_id, location)
        embed = discord.Embed(
            title="⛏️ Concession Granted",
            description=f"**{concession['name']}** at *{location}*",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Fee Paid", value=f"🪙 **{concession['fee']:,}**", inline=True)
        embed.add_field(name="Annual Fee", value=f"🪙 **{concession['annual']:,}**", inline=True)
        embed.add_field(name="Term", value=f"**{concession['years']} years**", inline=True)
        embed.add_field(name="Expires", value=f"<t:{int(expires.timestamp())}:D>", inline=True)
        embed.set_footer(text="Republic of Dravia | Mining Authority")
        await interaction.response.send_message(embed=embed)

    @mine_group.command(name="build", description="Build a mine facility")
    @app_commands.choices(tier=[
            app_commands.Choice(name="I — Artisanal Claim (🪙1,000, 10 pts)", value=1),
            app_commands.Choice(name="II — Small Mine (🪙3,000, 30 pts)", value=2),
            app_commands.Choice(name="III — Medium Mine (🪙7,500, 75 pts)", value=3),
            app_commands.Choice(name="IV — Large Mine (🪙15,000, 150 pts)", value=4),
            app_commands.Choice(name="V — Industrial Complex (🪙30,000, 300 pts)", value=5),
        ])
    async def mine_build(self, interaction: discord.Interaction, tier: int):
        user_id = str(interaction.user.id)
        concession = await self.get_concession(user_id)
        if not concession:
            await interaction.response.send_message("❌ Claim a concession first with `/mine claim`.", ephemeral=True)
            return
        if concession["tier"] > 0:
            await interaction.response.send_message("⚠️ You already have a mine built.", ephemeral=True)
            return

        tier_info = TIERS[tier]
        balance = await self.db.get_balance(user_id)
        if balance < tier_info["cost"]:
            await interaction.response.send_message(
                f"❌ Construction costs 🪙 {tier_info['cost']:,}. You have 🪙 {balance:,}.", ephemeral=True
            )
            return

        await self.db.remove_balance(user_id, tier_info["cost"], "mine_construction", f"Build {tier_info['name']}")
        royalty = min(MINERALS.values(), key=lambda m: m["royalty"])["royalty"]
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE mining_concessions SET tier = ?, daily_points = ?, rehabilitation_bond = ? WHERE id = ?",
                (tier, tier_info["points"], tier_info["bond"], concession["id"]),
            )
            await db.commit()

        embed = discord.Embed(
            title="⛏️ Mine Constructed",
            description=f"**{tier_info['name']}** opened",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Cost", value=f"🪙 **{tier_info['cost']:,}**", inline=True)
        embed.add_field(name="Capacity", value=f"**{tier_info['points']} pts/day**", inline=True)
        embed.add_field(name="Rehabilitation Bond", value=f"🪙 **{tier_info['bond']:,}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @mine_group.command(name="produce", description="Extract minerals")
    @app_commands.describe(mineral="Mineral to extract", quantity="Quantity")
    @app_commands.choices(mineral=[app_commands.Choice(name=m, value=m) for m in MINERALS])
    async def mine_produce(self, interaction: discord.Interaction, mineral: str, quantity: int):
        user_id = str(interaction.user.id)
        concession = await self.get_concession(user_id)
        if not concession or concession["tier"] <= 0:
            await interaction.response.send_message("❌ Build a mine first.", ephemeral=True)
            return
        if quantity <= 0:
            await interaction.response.send_message("❌ Quantity must be positive.", ephemeral=True)
            return

        mineral_info = MINERALS[mineral]
        cost_points = mineral_info["points"] * quantity
        if cost_points > concession["daily_points"]:
            await interaction.response.send_message(
                f"❌ Extracting {quantity}× {mineral} costs {cost_points} pts but capacity is {concession['daily_points']} pts/day.",
                ephemeral=True,
            )
            return

        royalty = int(cost_points * mineral_info["royalty"] * 10)  # royalty scaled to Ovi value
        balance = await self.db.get_balance(user_id)
        if balance < royalty:
            await interaction.response.send_message(
                f"❌ Royalty due is 🪙 {royalty:,}. You have 🪙 {balance:,}.", ephemeral=True
            )
            return

        if royalty > 0:
            await self.db.remove_balance(user_id, royalty, "royalty", f"Royalty on {mineral}")

        # Store extracted minerals as a "stockpile" via transactions description
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT minerals FROM mining_concessions WHERE id = ?", (concession["id"],)
            ) as cursor:
                current = (await cursor.fetchone())["minerals"] or ""
            stockpile = dict(item.split(":") for item in current.split(",") if item) if current else {}
            stockpile[mineral] = str(int(stockpile.get(mineral, 0)) + quantity)
            new_minerals = ",".join(f"{k}:{v}" for k, v in stockpile.items())
            await db.execute(
                "UPDATE mining_concessions SET minerals = ? WHERE id = ?", (new_minerals, concession["id"])
            )
            await db.commit()

        embed = discord.Embed(
            title="⛏️ Extraction Complete",
            description=f"**{quantity}× {mineral}** extracted",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Points Used", value=f"**{cost_points}/{concession['daily_points']}**", inline=True)
        embed.add_field(name="Royalty Paid", value=f"🪙 **{royalty:,}** ({mineral_info['royalty']*100:.0f}%)", inline=True)
        embed.set_footer(text="Republic of Dravia | Mining Authority")
        await interaction.response.send_message(embed=embed)

    @mine_group.command(name="refine", description="Refine raw minerals into finished goods")
    @app_commands.describe(mineral="Raw mineral", quantity="Quantity to refine")
    @app_commands.choices(mineral=[app_commands.Choice(name=k, value=k) for k in REFINING])
    async def mine_refine(self, interaction: discord.Interaction, mineral: str, quantity: int):
        user_id = str(interaction.user.id)
        concession = await self.get_concession(user_id)
        if not concession:
            await interaction.response.send_message("❌ You have no concession.", ephemeral=True)
            return
        if quantity <= 0:
            await interaction.response.send_message("❌ Quantity must be positive.", ephemeral=True)
            return

        # Check stockpile
        stockpile = dict(
            item.split(":") for item in (concession["minerals"] or "").split(",") if item
        ) if concession["minerals"] else {}
        available = int(stockpile.get(mineral, 0))
        if available < quantity:
            await interaction.response.send_message(
                f"❌ You only have {available}× {mineral}. Extract more with `/mine produce`.", ephemeral=True
            )
            return

        product, value_add = REFINING[mineral]
        stockpile[mineral] = str(available - quantity)
        new_minerals = ",".join(f"{k}:{v}" for k, v in stockpile.items() if int(v) > 0)

        # Pay the value add per unit refined
        payout = value_add * quantity
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE mining_concessions SET minerals = ? WHERE id = ?", (new_minerals, concession["id"])
            )
            await db.commit()
        await self.db.add_balance(user_id, payout, "refining", f"Refined {quantity}× {mineral} -> {product}")

        embed = discord.Embed(
            title="🏭 Refining Complete",
            description=f"**{quantity}× {mineral} → {quantity}× {product}**",
            color=COLOR_GOLD,
        )
        embed.add_field(name="Value Added", value=f"🪙 **{payout:,}**", inline=True)
        embed.add_field(name="Stockpile Left", value=f"**{available - quantity}× {mineral}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @mine_group.command(name="status", description="View your concession and mine status")
    async def mine_status(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        concession = await self.get_concession(user_id)
        if not concession:
            await interaction.response.send_message(
                "❌ You hold no concession. Use `/mine claim`.", ephemeral=True
            )
            return

        tier_info = TIERS.get(concession["tier"])
        concession_info = CONCESSIONS.get(concession["concession_type"], {})
        expires = datetime.fromisoformat(concession["expires_at"])

        embed = discord.Embed(title="⛏️ Concession Status", color=COLOR_ACCENT)
        embed.add_field(name="Type", value=concession_info.get("name", concession["concession_type"]), inline=True)
        embed.add_field(name="Location", value=concession["location"], inline=True)
        embed.add_field(name="Facility", value=tier_info["name"] if tier_info else "Not built", inline=True)
        embed.add_field(name="Daily Capacity", value=f"**{concession['daily_points']} pts**", inline=True)
        embed.add_field(name="Bond", value=f"🪙 **{concession['rehabilitation_bond']:,}**", inline=True)
        embed.add_field(name="Expires", value=f"<t:{int(expires.timestamp())}:D>", inline=True)
        embed.add_field(name="Stockpile", value=concession["minerals"] or "Empty", inline=False)
        embed.set_footer(text="Republic of Dravia | Mining Authority")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @mine_group.command(name="safety", description="Run a safety inspection")
    async def mine_safety(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        concession = await self.get_concession(user_id)
        if not concession or concession["tier"] <= 0:
            await interaction.response.send_message("❌ You have no operating mine.", ephemeral=True)
            return

        checks = ["Ventilation", "Ground Control", "Gas Detection", "Escape Routes", "First Aid", "Safety Officer"]
        passed = random.randint(1, len(checks))
        failed = [c for c in checks if c not in checks[:passed]]

        if failed:
            embed = discord.Embed(
                title="⚠️ Safety Inspection — Deficiencies Found",
                description=f"Failed: **{', '.join(failed)}**",
                color=COLOR_CRIMSON,
            )
            embed.add_field(name="Required", value="Remediate before next extraction cycle.", inline=False)
        else:
            embed = discord.Embed(
                title="✅ Safety Inspection Passed",
                description="All statutory safety systems operational.",
                color=COLOR_ACCENT,
            )
        embed.set_footer(text="Republic of Dravia | Mining Safety Inspectorate")
        audit_log.info("Safety inspection by %s: passed=%s", user_id, passed)
        await interaction.response.send_message(embed=embed)

    @mine_group.command(name="bond", description="View your rehabilitation bond")
    async def mine_bond(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        concession = await self.get_concession(user_id)
        if not concession:
            await interaction.response.send_message("❌ You hold no concession.", ephemeral=True)
            return
        tier_info = TIERS.get(concession["tier"])
        embed = discord.Embed(title="🔒 Rehabilitation Bond", color=COLOR_GOLD)
        embed.add_field(name="Bond Held", value=f"🪙 **{concession['rehabilitation_bond']:,}**", inline=True)
        embed.add_field(
            name="Schedule",
            value="Artisanal 500 | Small 1,500 | Medium 5,000 | Large 15,000 | Industrial 30,000",
            inline=False,
        )
        embed.set_footer(text="Refundable on approved mine closure")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @mine_group.command(name="close", description="File a closure plan and close your mine")
    async def mine_close(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        concession = await self.get_concession(user_id)
        if not concession:
            await interaction.response.send_message("❌ You hold no concession.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            await db.execute("UPDATE mining_concessions SET is_active = 0 WHERE id = ?", (concession["id"],))
            await db.commit()

        audit_log.info("Mine closure filed by %s", user_id)
        embed = discord.Embed(
            title="⛏️ Closure Plan Filed",
            description="Your concession has been surrendered. Rehabilitation bond returned per schedule.",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Bond Refund", value=f"🪙 **{concession['rehabilitation_bond']:,}**", inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Mining(bot))
