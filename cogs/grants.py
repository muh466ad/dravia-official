"""Dravia State Bot - Grants & Assistance Commands"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import aiosqlite
import os

from config import COLOR_ACCENT, COLOR_GOLD
from utils.calendar import stamp
from database import Database

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Grant programs from Dravian law
GRANT_PROGRAMS = {
    "citizen": {
        "name": "Universal Citizen Grant",
        "amount": 2000,
        "description": "Every citizen gets 2,000 Ovi — no questions asked",
        "one_time": True
    },
    "business": {
        "name": "Business Starter Package",
        "amount": 5000,
        "description": "Start your own business with 5,000 Ovi!",
        "one_time": True
    },
    "stock": {
        "name": "Stock Market Entry Bonus",
        "amount": 1000,
        "description": "Get matched 1:1 on your first stock purchase — up to 1,000 Ovi!",
        "one_time": True
    },
    "agriculture": {
        "name": "Agricultural Subsidy",
        "amount": 1000,
        "description": "1,000 Ovi for every farmer!",
        "one_time": True
    },
    "education": {
        "name": "Education Fund",
        "amount": 2500,
        "description": "Get 50% of your tuition back — up to 2,500 Ovi!",
        "one_time": True
    }
}

class Grants(commands.Cog):
    """Grants and assistance commands."""
    
    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)
    
    async def has_claimed_grant(self, user_id: str, program: str) -> bool:
        """Check if user has claimed a grant."""
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id FROM grants WHERE user_id = ? AND program_name = ?",
                (user_id, program)
            ) as cursor:
                return await cursor.fetchone() is not None
    
    async def add_grant(self, user_id: str, program: str, amount: int):
        """Record and give grant to user."""
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO grants (user_id, program_name, amount, claimed_at) VALUES (?, ?, ?, ?)",
                (user_id, program, amount, datetime.now().isoformat())
            )
            await db.commit()
    
    @app_commands.command(name="grant", description="Claim a government grant")
    @app_commands.describe(program="The grant program to claim")
    @app_commands.choices(program=[
        app_commands.Choice(name="Universal Citizen Grant (2,000 Ovi)", value="citizen"),
        app_commands.Choice(name="Business Starter Package (5,000 Ovi)", value="business"),
        app_commands.Choice(name="Stock Market Entry Bonus (1,000 Ovi)", value="stock"),
        app_commands.Choice(name="Agricultural Subsidy (1,000 Ovi)", value="agriculture"),
        app_commands.Choice(name="Education Fund (2,500 Ovi)", value="education")
    ])
    async def claim_grant(self, interaction: discord.Interaction, program: str):
        """Claim a grant."""
        user_id = str(interaction.user.id)
        
        if program not in GRANT_PROGRAMS:
            await interaction.response.send_message("❌ Invalid grant program.", ephemeral=True)
            return
        
        grant_info = GRANT_PROGRAMS[program]
        
        # Check if already claimed
        if await self.has_claimed_grant(user_id, program):
            embed = discord.Embed(
                title="⚠️ Already Claimed",
                description=f"You have already claimed the **{grant_info['name']}**.",
                color=COLOR_GOLD
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check eligibility - for citizen grant, must be a citizen
        if program == "citizen":
            async with await self.db.get_connection() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT citizen_id FROM citizens WHERE discord_id = ?",
                    (user_id,)
                ) as cursor:
                    citizen = await cursor.fetchone()
            
            if not citizen:
                await interaction.response.send_message(
                    "❌ You must be a Dravian citizen to claim this grant. Use `/apply` first!",
                    ephemeral=True
                )
                return
        
        # Give the grant
        await self.db.add_balance(user_id, grant_info["amount"], "grant", grant_info["name"])
        await self.add_grant(user_id, program, grant_info["amount"])
        
        new_balance = await self.db.get_balance(user_id)
        
        embed = discord.Embed(
            title="✅ Grant Approved!",
            description=f"**{grant_info['name']}**",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Amount", value=f"🪙 **{grant_info['amount']:,}**", inline=True)
        embed.add_field(name="New Balance", value=f"🪙 **{new_balance:,}**", inline=True)
        embed.set_footer(text="Republic of Dravia | Cygnus Decree")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="grants", description="View available grants")
    @app_commands.describe(view_type="What to view")
    @app_commands.choices(view_type=[
        app_commands.Choice(name="List All Programs", value="list"),
        app_commands.Choice(name="My Claims", value="mine")
    ])
    async def list_grants(self, interaction: discord.Interaction, view_type: str = "list"):
        """List grants."""
        if view_type == "list":
            embed = discord.Embed(
                title="🏦 Dravia Assistance Programs",
                description="The government has **1.6 MILLION Ovi** for citizens!",
                color=COLOR_GOLD
            )
            
            for key, info in GRANT_PROGRAMS.items():
                embed.add_field(
                    name=f"{info['name']}",
                    value=f"🪙 **{info['amount']:,}** Ovi\n_{info['description']}_",
                    inline=False
                )
            
            embed.set_footer(text="Republic of Dravia | One-time claim per program")
        
        else:  # mine
            user_id = str(interaction.user.id)
            
            async with await self.db.get_connection() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT program_name, amount, claimed_at FROM grants WHERE user_id = ?",
                    (user_id,)
                ) as cursor:
                    claims = await cursor.fetchall()
            
            if not claims:
                embed = discord.Embed(
                    title="📋 Your Grants",
                    description="You haven't claimed any grants yet.",
                    color=COLOR_ACCENT
                )
            else:
                embed = discord.Embed(
                    title="📋 Your Claimed Grants",
                    color=COLOR_ACCENT
                )
                
                total = 0
                for claim in claims:
                    embed.add_field(
                        name=GRANT_PROGRAMS.get(claim["program_name"], {}).get("name", claim["program_name"]),
                        value=f"🪙 **{claim['amount']:,}** — {stamp(claim['claimed_at'], '%d %b %Y')}",
                        inline=False
                    )
                    total += claim["amount"]
                
                embed.add_field(name="Total Received", value=f"🪙 **{total:,}**", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Grants(bot))