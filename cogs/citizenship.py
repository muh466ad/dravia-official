"""Dravia State Bot - Citizenship Commands"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import random
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.calendar import stamp

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

def generate_citizen_id():
    """Generate a unique Dravian citizen ID."""
    year = datetime.now().year
    rand_num = random.randint(100000, 999999)
    return f"DRV-{year}-{rand_num}"

class Citizenship(commands.Cog):
    """Citizenship commands for Dravia."""
    
    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)
    
    async def get_or_create_citizen(self, user_id: str, guild_id: str, full_name: str = None, dob: str = None):
        """Get or create a citizen record."""
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM citizens WHERE discord_id = ?", (user_id,)
            ) as cursor:
                citizen = await cursor.fetchone()
            
            if not citizen and full_name and dob:
                citizen_id = generate_citizen_id()
                issued_at = datetime.now().isoformat()
                avatar_url = str(self.bot.get_user(int(user_id)).display_avatar.url) if self.bot.get_user(int(user_id)) else None
                
                await db.execute(
                    """INSERT INTO citizens (discord_id, citizen_id, full_name, date_of_birth, issued_at, guild_id, avatar_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, citizen_id, full_name, dob, issued_at, guild_id, avatar_url)
                )
                await db.commit()
                
                async with db.execute(
                    "SELECT * FROM citizens WHERE discord_id = ?", (user_id,)
                ) as cursor:
                    citizen = await cursor.fetchone()
            
            return dict(citizen) if citizen else None
    
    @app_commands.command(name="apply", description="Apply for Dravian Citizenship")
    @app_commands.describe(
        fullname="Your full name (as it will appear on ID)",
        dateofbirth="Your date of birth (DD/MM/YYYY)"
    )
    async def apply(self, interaction: discord.Interaction, fullname: str, dateofbirth: str):
        """Apply for citizenship."""
        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild.id)
        
        # Validate DOB format
        try:
            day, month, year = map(int, dateofbirth.split('/'))
            dob_date = datetime(year, month, day)
            if dob_date > datetime.now():
                await interaction.response.send_message("❌ Invalid date: Cannot be in the future.", ephemeral=True)
                return
            if year < 1900:
                await interaction.response.send_message("❌ Invalid date: Year must be after 1900.", ephemeral=True)
                return
        except:
            await interaction.response.send_message(
                "❌ Invalid date format. Use **DD/MM/YYYY** (e.g., 15/03/1998)",
                ephemeral=True
            )
            return
        
        # Check if already a citizen
        existing = await self.get_or_create_citizen(user_id, guild_id)
        
        if existing:
            embed = discord.Embed(
                title="⚠️ Already a Citizen",
                description=f"You already have a Dravian ID: **{existing['citizen_id']}**\nUse `/myid` to view it.",
                color=COLOR_GOLD
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create citizen
        citizen = await self.get_or_create_citizen(user_id, guild_id, fullname.strip(), dateofbirth)
        
        # Give starting bonus
        await self.db.create_user(user_id)
        
        embed = discord.Embed(
            title="🏛️ Citizenship Approved!",
            description=f"Welcome to the Republic of Dravia, **{fullname}**!",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Citizen ID", value=f"`{citizen['citizen_id']}`", inline=True)
        embed.add_field(name="Status", value="✅ Active", inline=True)
        embed.add_field(name="Starting Bonus", value="🪙 500 Ovi", inline=True)
        embed.set_footer(text="Ministry of the Interior | Republic of Dravia")
        
        await interaction.response.send_message(embed=embed)
        
        # Announce in channel
        try:
            await interaction.channel.send(
                f"🎉 **{interaction.user.display_name}** has been granted **Dravian Citizenship**! Welcome to the Republic! 🇩🇷"
            )
        except:
            pass
    
    @app_commands.command(name="myid", description="View your Dravian Citizenship ID")
    async def myid(self, interaction: discord.Interaction):
        """View your ID card."""
        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild.id)
        
        citizen = await self.get_or_create_citizen(user_id, guild_id)
        
        if not citizen:
            embed = discord.Embed(
                title="❌ No ID Found",
                description="You don't have a Dravian ID yet. Use `/apply` to register!",
                color=COLOR_CRIMSON
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if active
        status = "✅ Active" if citizen["is_active"] else "❌ Revoked"
        
        embed = discord.Embed(
            title="🪪 Dravian Citizenship ID",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Citizen ID", value=f"`{citizen['citizen_id']}`", inline=True)
        embed.add_field(name="Full Name", value=citizen["full_name"], inline=True)
        embed.add_field(name="Date of Birth", value=citizen["date_of_birth"], inline=True)
        embed.add_field(name="Nationality", value=citizen["nationality"], inline=True)
        embed.add_field(name="Rank", value=citizen["rank"], inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Issued", value=stamp(citizen["issued_at"], "%d %B %Y"), inline=True)
        embed.set_thumbnail(interaction.user.display_avatar.url)
        embed.set_footer(text="Ministry of the Interior | Republic of Dravia")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="lookup", description="Look up a citizen's ID (Admin)")
    @app_commands.describe(user="The user to look up")
    @app_commands.default_permissions(manage_guild=True)
    async def lookup(self, interaction: discord.Interaction, user: discord.User):
        """Admin lookup citizen."""
        user_id = str(user.id)
        guild_id = str(interaction.guild.id)
        
        citizen = await self.get_or_create_citizen(user_id, guild_id)
        
        if not citizen:
            await interaction.response.send_message(
                f"❌ No citizen record found for {user.display_name}",
                ephemeral=True
            )
            return
        
        status = "✅ Active" if citizen["is_active"] else "❌ Revoked"
        
        embed = discord.Embed(
            title="🔍 Citizen Lookup",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Discord", value=user.mention, inline=True)
        embed.add_field(name="Citizen ID", value=f"`{citizen['citizen_id']}`", inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Full Name", value=citizen["full_name"], inline=True)
        embed.add_field(name="Rank", value=citizen["rank"], inline=True)
        embed.add_field(name="Issued", value=stamp(citizen["issued_at"], "%d %B %Y"), inline=True)
        embed.set_thumbnail(user.display_avatar.url)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="citizens", description="List all citizens (Admin)")
    @app_commands.describe(page="Page number")
    @app_commands.default_permissions(manage_guild=True)
    async def citizens_list(self, interaction: discord.Interaction, page: int = 1):
        """List all citizens."""
        if page < 1:
            page = 1
        
        guild_id = str(interaction.guild.id)
        
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM citizens WHERE guild_id = ? ORDER BY id DESC LIMIT 10 OFFSET ?",
                (guild_id, (page - 1) * 10)
            ) as cursor:
                citizens = await cursor.fetchall()
            
            async with db.execute(
                "SELECT COUNT(*) as count FROM citizens WHERE guild_id = ?",
                (guild_id,)
            ) as cursor:
                total = (await cursor.fetchone())["count"]
        
        if not citizens:
            await interaction.response.send_message("No citizens registered yet.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🏛️ Dravian Citizens Registry",
            description=f"Total citizens: **{total}**",
            color=COLOR_GOLD
        )
        
        for c in citizens:
            status = "✅" if c["is_active"] else "❌"
            embed.add_field(
                name=f"{status} {c['full_name']}",
                value=f"ID: `{c['citizen_id']}` | Rank: {c['rank']}",
                inline=False
            )
        
        embed.set_footer(text=f"Page {page} of {(total - 1) // 10 + 1}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="setrank", description="Set a citizen's rank (Admin)")
    @app_commands.describe(
        user="The citizen",
        rank="New rank"
    )
    @app_commands.choices(rank=[
        app_commands.Choice(name="Citizen", value="Citizen"),
        app_commands.Choice(name="Resident", value="Resident"),
        app_commands.Choice(name="Noble", value="Noble"),
        app_commands.Choice(name="Official", value="Official"),
        app_commands.Choice(name="Minister", value="Minister"),
        app_commands.Choice(name="Chancellor", value="Chancellor")
    ])
    @app_commands.default_permissions(manage_guild=True)
    async def setrank(self, interaction: discord.Interaction, user: discord.User, rank: str):
        """Set citizen rank."""
        user_id = str(user.id)
        guild_id = str(interaction.guild.id)
        
        citizen = await self.get_or_create_citizen(user_id, guild_id)
        
        if not citizen:
            await interaction.response.send_message(
                "❌ That user does not have a Dravian ID.",
                ephemeral=True
            )
            return
        
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE citizens SET rank = ? WHERE discord_id = ?",
                (rank, user_id)
            )
            await db.commit()
        
        await interaction.response.send_message(
            f"✅ {user.display_name}'s rank has been updated to **{rank}**.",
            ephemeral=True
        )


    marriage_group = app_commands.Group(name="marriage", description="Civil registry of marriages")

    @marriage_group.command(name="marry", description="Enter a marriage at the civil registry")
    @app_commands.describe(partner="Who you are marrying")
    async def marriage_marry(self, interaction: discord.Interaction, partner: discord.Member):
        if partner.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ You cannot marry yourself.", ephemeral=True)
            return
        me, them = str(interaction.user.id), str(partner.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM marriages WHERE status = 'active' "
                "AND (partner1_id IN (?, ?) OR partner2_id IN (?, ?))",
                (me, them, me, them),
            ) as cursor:
                taken = (await cursor.fetchone())[0]
            if taken:
                await interaction.response.send_message(
                    "❌ You or your partner is already married (or the divorce is pending).",
                    ephemeral=True,
                )
                return
            cursor = await db.execute(
                "INSERT INTO marriages (partner1_id, partner2_id, married_at, status) "
                "VALUES (?, ?, date('now'), 'active')",
                (me, them),
            )
            marriage_id = cursor.lastrowid
            await db.commit()
        embed = discord.Embed(
            title="💍 Marriage Registered",
            description=f"**{interaction.user.display_name}** and **{partner.display_name}** "
                        f"are married in the eyes of the Republic.",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Registry entry", value=f"#{marriage_id}", inline=True)
        embed.add_field(name="Record", value="Use `/marriage status` to view it.", inline=True)
        await interaction.response.send_message(embed=embed)

    @marriage_group.command(name="divorce", description="Dissolve your marriage")
    async def marriage_divorce(self, interaction: discord.Interaction):
        me = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT marriage_id, partner1_id, partner2_id FROM marriages "
                "WHERE status = 'active' AND (partner1_id = ? OR partner2_id = ?)",
                (me, me),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                await interaction.response.send_message(
                    "❌ You have no active marriage to dissolve.", ephemeral=True)
                return
            marriage_id, partner1_id, partner2_id = row
            cursor = await db.execute(
                "UPDATE marriages SET status = 'divorced' WHERE marriage_id = ? "
                "AND status = 'active'", (marriage_id,)
            )
            changed = cursor.rowcount
            await db.commit()
        if changed != 1:
            await interaction.response.send_message(
                "❌ That marriage was just dissolved.", ephemeral=True)
            return
        other_id = partner2_id if partner1_id == me else partner1_id
        embed = discord.Embed(
            title="💔 Marriage Dissolved",
            description=f"<@{me}> and <@{other_id}> are no longer married.",
            color=COLOR_CRIMSON,
        )
        embed.add_field(name="Registry entry", value=f"#{marriage_id}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @marriage_group.command(name="status", description="Marriage record")
    @app_commands.describe(user="Person to look up (defaults to you)")
    async def marriage_status(self, interaction: discord.Interaction,
                              user: discord.Member = None):
        target = user or interaction.user
        me = str(target.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT marriage_id, partner1_id, partner2_id, married_at FROM marriages "
                "WHERE status = 'active' AND (partner1_id = ? OR partner2_id = ?) "
                "ORDER BY marriage_id DESC LIMIT 1",
                (me, me),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            embed = discord.Embed(
                title="💍 Civil Registry",
                description=f"**{target.display_name}** is not married.",
                color=COLOR_GOLD,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        marriage_id, partner1_id, partner2_id, married_at = row
        other_id = partner2_id if partner1_id == me else partner1_id
        embed = discord.Embed(
            title="💍 Marriage Record",
            description=f"**{target.display_name}** and <@{other_id}>",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Registry entry", value=f"#{marriage_id}", inline=True)
        embed.add_field(name="Married on", value=stamp(married_at), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="reputation", description="A citizen's civic standing")
    @app_commands.describe(user="Citizen to inspect (defaults to you)")
    async def reputation(self, interaction: discord.Interaction,
                         user: discord.Member = None):
        target = user or interaction.user
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT score, last_updated FROM reputation WHERE user_id = ?",
                (str(target.id),),
            ) as cursor:
                row = await cursor.fetchone()
        score = row[0] if row else 0
        if score >= 1000:
            standing = "Exemplary — the Republic cites them as an example"
        elif score >= 500:
            standing = "Distinguished — trusted by their community"
        elif score >= 100:
            standing = "Standing — a reliable citizen"
        elif score >= -100:
            standing = "Ordinary — no note on record"
        else:
            standing = "Under scrutiny — the registry flags their record"
        embed = discord.Embed(
            title=f"⭐ Reputation — {target.display_name}",
            color=COLOR_GOLD,
        )
        embed.add_field(name="Score", value=f"**{score:,}**", inline=True)
        embed.add_field(name="Standing", value=standing, inline=False)
        if row and row[1]:
            embed.add_field(name="Last updated", value=stamp(row[1]), inline=True)
        embed.set_footer(text="Reputation is earned through deeds across Dravia")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Citizenship(bot))