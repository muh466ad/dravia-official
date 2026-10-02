"""Dravia State Bot - Economy Commands"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import date, datetime
import os

from config import (
    COLOR_ACCENT, COLOR_GOLD, DAILY_UBI_AMOUNT, WEEKLY_UBI_AMOUNT,
    STARTING_BALANCE, TAX_RATE_0_500, TAX_RATE_501_2000, TAX_RATE_2001_5000, TAX_RATE_5000_PLUS
)
from database import Database

# Get database path from environment
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

class Economy(commands.Cog):
    """Core economy commands for Dravia."""
    
    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)
    
    @app_commands.command(name="balance", description="Check your or another user's balance")
    @app_commands.describe(user="The user to check (leave empty for yourself)")
    async def balance(self, interaction: discord.Interaction, user: discord.User = None):
        """Check balance command."""
        target = user or interaction.user
        await self.db.create_user(str(target.id))
        
        balance = await self.db.get_balance(str(target.id))
        
        embed = discord.Embed(
            title=f"💰 Balance",
            color=COLOR_GOLD
        )
        embed.add_field(
            name="🪙 Ovi" if balance == 1 else "🪙 Ovi",
            value=f"**{balance:,}**",
            inline=False
        )
        
        if target == interaction.user:
            embed.description = "Your current balance"
        else:
            embed.description = f"{target.display_name}'s balance"
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="pay", description="Transfer Ovi to another user")
    @app_commands.describe(user="The user to pay", amount="Amount of Ovi to transfer")
    async def pay(self, interaction: discord.Interaction, user: discord.User, amount: int):
        """Transfer Ovi to another user."""
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        
        if user.id == interaction.user.id:
            await interaction.response.send_message("❌ You cannot pay yourself.", ephemeral=True)
            return
        
        sender_id = str(interaction.user.id)
        recipient_id = str(user.id)
        
        # Ensure both users exist
        await self.db.create_user(sender_id)
        await self.db.create_user(recipient_id)
        
        sender_balance = await self.db.get_balance(sender_id)
        
        if sender_balance < amount:
            await interaction.response.send_message(
                f"❌ Insufficient funds. You have {sender_balance:,} Ovi.",
                ephemeral=True
            )
            return
        
        # Process transfer
        await self.db.transfer(sender_id, recipient_id, amount, f"Payment to {user.name}")
        
        embed = discord.Embed(
            title="✅ Transfer Complete",
            color=COLOR_ACCENT
        )
        embed.add_field(name="From", value=f"{interaction.user.mention}", inline=True)
        embed.add_field(name="To", value=f"{user.mention}", inline=True)
        embed.add_field(name="Amount", value=f"🪙 **{amount:,}**", inline=False)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="daily", description="Claim your daily UBI (50 Ovi)")
    async def daily(self, interaction: discord.Interaction):
        """Claim daily UBI."""
        user_id = str(interaction.user.id)
        await self.db.create_user(user_id)
        
        # Check cooldown
        last_claimed = await self.db.get_cooldown(user_id, "daily")
        today = date.today().isoformat()
        
        if last_claimed == today:
            await interaction.response.send_message(
                "⏳ You've already claimed your daily UBI today. Come back tomorrow!",
                ephemeral=True
            )
            return
        
        # Add balance and set cooldown
        await self.db.add_balance(user_id, DAILY_UBI_AMOUNT, "daily_ubi", "Daily UBI claim")
        await self.db.set_cooldown(user_id, "daily")
        
        new_balance = await self.db.get_balance(user_id)
        
        embed = discord.Embed(
            title="✅ Daily UBI Claimed!",
            description=f"You received **{DAILY_UBI_AMOUNT}** Ovi 🪙",
            color=COLOR_ACCENT
        )
        embed.add_field(name="New Balance", value=f"🪙 **{new_balance:,}**", inline=False)
        embed.set_footer(text="Republic of Dravia | Daily UBI available again in 24 hours")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="weekly", description="Claim your weekly UBI (350 Ovi)")
    async def weekly(self, interaction: discord.Interaction):
        """Claim weekly UBI."""
        user_id = str(interaction.user.id)
        await self.db.create_user(user_id)
        
        # Check cooldown - weekly uses different command name
        last_claimed = await self.db.get_cooldown(user_id, "weekly")
        today = date.today().isoformat()
        
        if last_claimed == today:
            await interaction.response.send_message(
                "⏳ You've already claimed your weekly UBI today.",
                ephemeral=True
            )
            return
        
        # Add balance and set cooldown
        await self.db.add_balance(user_id, WEEKLY_UBI_AMOUNT, "weekly_ubi", "Weekly UBI claim")
        await self.db.set_cooldown(user_id, "weekly")
        
        new_balance = await self.db.get_balance(user_id)
        
        embed = discord.Embed(
            title="✅ Weekly UBI Claimed!",
            description=f"You received **{WEEKLY_UBI_AMOUNT}** Ovi 🪙",
            color=COLOR_ACCENT
        )
        embed.add_field(name="New Balance", value=f"🪙 **{new_balance:,}**", inline=False)
        embed.set_footer(text="Republic of Dravia | Weekly UBI available every Sunday")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="leaderboard", description="View the richest citizens")
    @app_commands.describe(page="Page number")
    async def leaderboard(self, interaction: discord.Interaction, page: int = 1):
        """View richest users."""
        if page < 1:
            page = 1
        
        limit = 10
        offset = (page - 1) * limit
        
        leaderboard_data = await self.db.get_leaderboard(limit + 1)  # +1 to check for more
        has_more = len(leaderboard_data) > limit
        leaderboard_data = leaderboard_data[:limit]
        
        if not leaderboard_data:
            await interaction.response.send_message(
                "📊 No citizens found yet!",
                ephemeral=True
            )
            return
        
        # Build leaderboard embed
        embed = discord.Embed(
            title="📊 Dravia Rich List",
            description="Top citizens by Ovi holdings",
            color=COLOR_GOLD
        )
        
        for i, row in enumerate(leaderboard_data, start=offset + 1):
            user_id = row["user_id"]
            balance = row["balance"]
            
            # Try to get user from cache
            user = self.bot.get_user(int(user_id))
            name = user.display_name if user else f"User {user_id[:8]}..."
            
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"**{i}.**"
            
            embed.add_field(
                name=f"{medal} {name}",
                value=f"🪙 **{balance:,}**",
                inline=True
            )
        
        embed.set_footer(text=f"Page {page}" + (" | More pages available" if has_more else ""))
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="economy", description="View economy statistics")
    @app_commands.describe(stats_type="Type of stats to view")
    @app_commands.choices(stats_type=[
        app_commands.Choice(name="Overview", value="overview"),
        app_commands.Choice(name="History", value="history")
    ])
    async def economy_stats(self, interaction: discord.Interaction, stats_type: str = "overview"):
        """View economy statistics."""
        stats = await self.db.get_economy_stats()
        
        if stats_type == "overview":
            embed = discord.Embed(
                title="📈 Dravia Economy Statistics",
                color=COLOR_ACCENT
            )
            embed.add_field(name="Total Citizens", value=f"**{stats['total_users']:,}**", inline=True)
            embed.add_field(name="Total Money Supply", value=f"🪙 **{stats['total_money']:,}**", inline=True)
            embed.add_field(name="Average Balance", value=f"🪙 **{stats['avg_balance']:.0f}**", inline=True)
            embed.add_field(name="Starting Balance", value=f"🪙 **{STARTING_BALANCE}**", inline=True)
            embed.add_field(name="Daily UBI", value=f"🪙 **{DAILY_UBI_AMOUNT}**", inline=True)
            embed.add_field(name="Weekly UBI", value=f"🪙 **{WEEKLY_UBI_AMOUNT}**", inline=True)
            embed.set_footer(text="Republic of Dravia | Central Bank")
            
        else:  # history
            user_id = str(interaction.user.id)
            transactions = await self.db.get_transactions(user_id, 10)
            
            embed = discord.Embed(
                title="📜 Your Transaction History",
                color=COLOR_ACCENT
            )
            
            if not transactions:
                embed.description = "No transactions yet."
            else:
                for tx in transactions:
                    tx_type = tx["type"]
                    amount = tx["amount"]
                    desc = tx["description"] or ""
                    
                    if tx["from_user"] == user_id:
                        embed.add_field(
                            name=f"🔴 Sent - {amount:,} Ovi",
                            value=f"To: {tx['to_user'][:8]}... | {desc}",
                            inline=False
                        )
                    else:
                        embed.add_field(
                            name=f"🟢 Received - {amount:,} Ovi",
                            value=f"From: {tx['from_user'][:8]}... | {desc}",
                            inline=False
                        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # /tax check now lives in cogs/taxes.py (the /tax command group)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Economy(bot))