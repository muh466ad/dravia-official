"""Dravia State Bot - Tax System (Revenue Office)"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, date, timedelta
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.checks import requires_revenue
from utils.logger import audit_log, tx_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Weekly income tax brackets (Part 8)
INCOME_BRACKETS = [
    (500, 0.00),
    (2000, 0.03),
    (5000, 0.05),
    (float("inf"), 0.10),
]

# Annual wealth tax brackets
WEALTH_BRACKETS = [
    (100_000, 0.005),
    (500_000, 0.008),
    (1_000_000, 0.010),
    (float("inf"), 0.012),
]


def income_tax(amount: int) -> int:
    """Calculate weekly income tax (marginal brackets)."""
    tax = 0.0
    lower = 0
    for upper, rate in INCOME_BRACKETS:
        if amount > lower:
            taxed = min(amount, upper) - lower
            tax += taxed * rate
            lower = upper
        else:
            break
    return int(tax)


def wealth_tax(amount: int) -> int:
    """Calculate annual wealth tax."""
    if amount < 50_000:
        return 0
    tax = 0.0
    lower = 0
    for upper, rate in WEALTH_BRACKETS:
        if amount > lower:
            taxed = min(amount, upper) - lower
            tax += taxed * rate
            lower = upper
        else:
            break
    return int(tax)

class Taxes(commands.Cog):
    """Tax system for Dravia."""
    
    tax_group = app_commands.Group(name="tax", description="Tax commands and Revenue Office enforcement")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    async def add_tax(self, user_id: str, tax_type: str, amount: int) -> None:
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO taxes (user_id, tax_type, amount, week_start, paid, created_at) VALUES (?, ?, ?, ?, 0, ?)",
                (user_id, tax_type, amount, date.today().isoformat(), datetime.now().isoformat()),
            )
            await db.commit()

    async def unpaid_taxes(self, user_id: str) -> int:
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT SUM(amount) as total FROM taxes WHERE user_id = ? AND paid = 0", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] or 0

    @tax_group.command(name="check", description="Check your tax rate")
    async def tax_check(self, interaction: discord.Interaction):
        """Check tax rate based on weekly income."""
        user_id = str(interaction.user.id)
        await self.db.create_user(user_id)
        
        user = await self.db.get_user(user_id)
        total_earned = user["total_earned"] if user else 0
        
        if total_earned <= 500:
            bracket = "0%"
        elif total_earned <= 2000:
            bracket = "3%"
        elif total_earned <= 5000:
            bracket = "5%"
        else:
            bracket = "10%"
        
        embed = discord.Embed(title="🧾 Your Tax Information", color=COLOR_ACCENT)
        embed.add_field(name="Total Earned (all time)", value=f"🪙 **{total_earned:,}**", inline=True)
        embed.add_field(name="Current Tax Bracket", value=f"**{bracket}**", inline=True)
        embed.add_field(
            name="Tax Brackets",
            value="0-500: 0%\n501-2000: 3%\n2001-5000: 5%\n5000+: 10%",
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | Revenue Office")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tax_group.command(name="declare", description="File your weekly tax declaration")
    async def tax_declare(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await self.db.create_user(user_id)
        user = await self.db.get_user(user_id)
        weekly_earned = user["total_earned"] if user else 0
        # Estimate this week's income as recent transactions received
        txs = await self.db.get_transactions(user_id, 50)
        week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        weekly_income = sum(
            t["amount"] for t in txs
            if t["to_user"] == user_id and (t["created_at"] or "") >= week_start
        )
        owed = income_tax(weekly_income)
        await self.add_tax(user_id, "income", owed)
        audit_log.info("Tax declaration filed by %s: owed %s Ovi", user_id, owed)

        embed = discord.Embed(
            title="🧾 Declaration Filed",
            description=f"Weekly income: **🪙 {weekly_income:,}**",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Tax Owed", value=f"🪙 **{owed:,}**", inline=True)
        embed.add_field(name="Bracket", value=f"**{owed / weekly_income * 100:.1f}%**" if weekly_income else "**0%**", inline=True)
        embed.add_field(name="Pay Now", value="Use `/tax pay`", inline=False)
        embed.set_footer(text="Republic of Dravia | Revenue Office")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tax_group.command(name="pay", description="Pay your outstanding taxes")
    @app_commands.describe(amount="Amount to pay (leave empty for full amount)")
    async def tax_pay(self, interaction: discord.Interaction, amount: int = None):
        user_id = str(interaction.user.id)
        owed = await self.unpaid_taxes(user_id)
        if owed <= 0:
            await interaction.response.send_message("✅ You have no outstanding taxes.", ephemeral=True)
            return
        if amount is None or amount > owed:
            amount = owed
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return

        balance = await self.db.get_balance(user_id)
        if balance < amount:
            await interaction.response.send_message(
                f"❌ Insufficient funds. You owe {owed:,} Ovi and have {balance:,} Ovi.",
                ephemeral=True,
            )
            return

        await self.db.remove_balance(user_id, amount, "tax_payment", "Tax payment")
        async with await self.db.get_connection() as db:
            remaining = amount
            async with db.execute(
                "SELECT id, amount FROM taxes WHERE user_id = ? AND paid = 0 ORDER BY id", (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
            for row_id, row_amount in rows:
                if remaining <= 0:
                    break
                if remaining >= row_amount:
                    await db.execute("UPDATE taxes SET paid = 1 WHERE id = ?", (row_id,))
                    remaining -= row_amount
                else:
                    await db.execute("UPDATE taxes SET amount = amount - ? WHERE id = ?", (remaining, row_id))
                    remaining = 0
            await db.execute(
                "UPDATE users SET tax_paid = tax_paid + ? WHERE user_id = ?", (amount, user_id)
            )
            await db.commit()
        tx_log.info("Tax payment: user=%s amount=%s", user_id, amount)

        embed = discord.Embed(title="✅ Taxes Paid", color=COLOR_GOLD)
        embed.add_field(name="Amount Paid", value=f"🪙 **{amount:,}**", inline=True)
        embed.add_field(name="Remaining", value=f"🪙 **{max(0, owed - amount):,}**", inline=True)
        embed.set_footer(text="Republic of Dravia | Revenue Office")
        await interaction.response.send_message(embed=embed)

    @tax_group.command(name="history", description="View your tax history")
    async def tax_history(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM taxes WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title="📜 Tax History", color=COLOR_ACCENT)
        if not rows:
            embed.description = "No tax records yet."
        else:
            for r in rows:
                status = "✅ Paid" if r["paid"] else "⏳ Owed"
                embed.add_field(
                    name=f"{r['tax_type'].title()} — 🪙 {r['amount']:,}",
                    value=f"{status} | {(r['created_at'] or '')[:10]}",
                    inline=False,
                )
        embed.set_footer(text="Republic of Dravia | Revenue Office")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tax_group.command(name="wealth", description="View your annual wealth tax assessment")
    async def tax_wealth(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await self.db.create_user(user_id)
        balance = await self.db.get_balance(user_id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(savings), 0) FROM bank_accounts WHERE user_id = ?", (user_id,)
            ) as cursor:
                savings = (await cursor.fetchone())[0]
        total_wealth = balance + savings
        owed = wealth_tax(total_wealth)

        embed = discord.Embed(title="🏛️ Wealth Tax Assessment", color=COLOR_GOLD)
        embed.add_field(name="Wallet", value=f"🪙 **{balance:,}**", inline=True)
        embed.add_field(name="Bank", value=f"🪙 **{savings:,}**", inline=True)
        embed.add_field(name="Total Wealth", value=f"🪙 **{total_wealth:,}**", inline=True)
        embed.add_field(name="Annual Wealth Tax", value=f"🪙 **{owed:,}**", inline=False)
        embed.add_field(
            name="Brackets",
            value="50k–100k: 0.5%\n100k–500k: 0.8%\n500k–1M: 1.0%\n1M+: 1.2%",
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | Assessed annually on the 15th")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tax_group.command(name="estimate", description="Estimate your tax burden")
    async def tax_estimate(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await self.db.create_user(user_id)
        balance = await self.db.get_balance(user_id)
        weekly = income_tax(balance)  # estimate on current weekly capacity
        embed = discord.Embed(title="📊 Tax Burden Estimate", color=COLOR_ACCENT)
        embed.add_field(name="Estimated Weekly Income Tax", value=f"🪙 **{weekly:,}**", inline=True)
        embed.add_field(name="Estimated Annual Wealth Tax", value=f"🪙 **{wealth_tax(balance):,}**", inline=True)
        embed.add_field(
            name="Income Brackets",
            value="0–500: 0%\n501–2,000: 3%\n2,001–5,000: 5%\n5,000+: 10%",
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | Estimates only")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Revenue Office (enforcement) ---

    @tax_group.command(name="audit", description="Open a tax audit on a citizen")
    @app_commands.describe(user="Citizen to audit", reason="Reason for the audit")
    @requires_revenue
    async def tax_audit(self, interaction: discord.Interaction, user: discord.User, reason: str = "Routine audit"):
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO taxes (user_id, tax_type, amount, week_start, paid, created_at) VALUES (?, 'audit', 0, ?, 0, ?)",
                (str(user.id), date.today().isoformat(), datetime.now().isoformat()),
            )
            await db.commit()
        audit_log.info("Audit opened on %s by %s: %s", user.id, interaction.user.id, reason)
        embed = discord.Embed(
            title="🔍 Audit Opened",
            description=f"**Target:** {user.mention}\n**Reason:** {reason}",
            color=COLOR_CRIMSON,
        )
        embed.set_footer(text="Republic of Dravia | Revenue Office")
        await interaction.response.send_message(embed=embed)

    @tax_group.command(name="assess", description="Issue a tax assessment against a citizen")
    @app_commands.describe(user="Citizen", amount="Assessed amount")
    @requires_revenue
    async def tax_assess(self, interaction: discord.Interaction, user: discord.User, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        await self.add_tax(str(user.id), "assessment", amount)
        audit_log.info("Assessment of %s Ovi issued against %s by %s", amount, user.id, interaction.user.id)
        embed = discord.Embed(
            title="🧾 Assessment Issued",
            description=f"**{user.mention}** assessed for 🪙 **{amount:,}**",
            color=COLOR_CRIMSON,
        )
        await interaction.response.send_message(embed=embed)

    @tax_group.command(name="penalty", description="Issue a tax penalty")
    @app_commands.describe(user="Citizen", amount="Penalty amount", reason="Reason")
    @requires_revenue
    async def tax_penalty(self, interaction: discord.Interaction, user: discord.User, amount: int, reason: str):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        await self.add_tax(str(user.id), "penalty", amount)
        audit_log.info("Penalty %s Ovi against %s by %s: %s", amount, user.id, interaction.user.id, reason)
        embed = discord.Embed(
            title="⚠️ Penalty Issued",
            description=f"**{user.mention}** penalised 🪙 **{amount:,}**\nReason: {reason}",
            color=COLOR_CRIMSON,
        )
        await interaction.response.send_message(embed=embed)

    @tax_group.command(name="cross_reference", description="Cross-check a citizen's wealth vs income")
    @app_commands.describe(user="Citizen to cross-reference")
    @requires_revenue
    async def tax_cross_reference(self, interaction: discord.Interaction, user: discord.User):
        user_id = str(user.id)
        await self.db.create_user(user_id)
        record = await self.db.get_user(user_id)
        balance = await self.db.get_balance(user_id)
        earned = record["total_earned"] if record else 0
        ratio = (balance / earned) if earned else 0
        flag = "⚠️ Wealth exceeds recorded income — possible evasion" if ratio > 1.5 else "✅ Within expected range"
        embed = discord.Embed(title=f"🔎 Cross-Reference: {user.display_name}", color=COLOR_ACCENT)
        embed.add_field(name="Total Earned", value=f"🪙 **{earned:,}**", inline=True)
        embed.add_field(name="Current Wealth", value=f"🪙 **{balance:,}**", inline=True)
        embed.add_field(name="Wealth/Income Ratio", value=f"**{ratio:.2f}**", inline=True)
        embed.add_field(name="Finding", value=flag, inline=False)
        audit_log.info("Cross-reference on %s by %s", user.id, interaction.user.id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tax_group.command(name="hnwi", description="List high-net-worth individuals")
    @requires_revenue
    async def tax_hnwi(self, interaction: discord.Interaction):
        rows = await self.db.get_leaderboard(10)
        embed = discord.Embed(title="💎 HNWI Unit — Top Wealth", color=COLOR_GOLD)
        for i, row in enumerate(rows, 1):
            embed.add_field(
                name=f"{i}. User {row['user_id'][:8]}...",
                value=f"🪙 **{row['balance']:,}**",
                inline=True,
            )
        if not rows:
            embed.description = "No records."
        embed.set_footer(text="Republic of Dravia | HNWI Unit")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tax_group.command(name="publish", description="Publish the annual tax report")
    @requires_revenue
    async def tax_publish(self, interaction: discord.Interaction):
        stats = await self.db.get_economy_stats()
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT SUM(amount) as total FROM taxes WHERE paid = 1") as cursor:
                collected = (await cursor.fetchone())[0] or 0
            async with db.execute("SELECT COUNT(*) FROM citizens") as cursor:
                citizens = (await cursor.fetchone())[0]
        embed = discord.Embed(
            title="📊 Annual Revenue Report",
            description="Official publication of the Revenue Office",
            color=COLOR_GOLD,
        )
        embed.add_field(name="Tax Collected", value=f"🪙 **{collected:,}**", inline=True)
        embed.add_field(name="Money Supply", value=f"🪙 **{stats['total_money'] or 0:,}**", inline=True)
        embed.add_field(name="Registered Citizens", value=f"**{citizens}**", inline=True)
        embed.set_footer(text="Republic of Dravia | Revenue Office")
        await interaction.response.send_message(embed=embed)
        audit_log.info("Annual tax report published by %s", interaction.user.id)


async def setup(bot):
    await bot.add_cog(Taxes(bot))
