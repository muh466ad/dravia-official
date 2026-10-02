"""Dravia State Bot - Admin & Setup Commands"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON, STARTING_BALANCE
from database import Database
from utils.logger import admin_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Roles created by /setup (Permissions Matrix, Part 21)
MANAGED_ROLES = [
    "Citizen", "Student", "Farmer", "Trader", "Business Owner",
    "Civil Servant", "Police Officer", "Bank Staff", "Revenue Staff",
    "SEC", "Consumer Protection", "Curial", "Minister", "Journalist",
    "Homeowner",
]

CHANNELS = [
    ("📜-gazette", "Government Gazette & announcements"),
    ("📈-market", "Stock market & economy discussion"),
    ("👮-dispatch", "Police dispatch & duty"),
    ("🏛️-curia", "Curia legislative chamber"),
]

class Admin(commands.Cog):
    """Administrative commands."""
    
    admin_group = app_commands.Group(name="admin", description="Administrative commands")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    @app_commands.command(name="setup", description="Initial server configuration (Admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("❌ Run this in a server.", ephemeral=True)
            return

        created_roles = []
        for role_name in MANAGED_ROLES:
            if not discord.utils.get(interaction.guild.roles, name=role_name):
                try:
                    colour = COLOR_CRIMSON if role_name in ("Police Officer", "Minister", "Curial") else COLOR_GOLD
                    await interaction.guild.create_role(
                        name=role_name, colour=colour, reason="Dravia /setup"
                    )
                    created_roles.append(role_name)
                except Exception:
                    pass

        created_channels = []
        for name, _purpose in CHANNELS:
            clean = name.split("-", 1)[-1]
            if not discord.utils.get(interaction.guild.text_channels, name=clean):
                try:
                    await interaction.guild.create_text_channel(clean, reason="Dravia /setup")
                    created_channels.append(clean)
                except Exception:
                    pass

        admin_log.info(
            "Setup run by %s in %s: roles=%s channels=%s",
            interaction.user.id, interaction.guild.id, created_roles, created_channels,
        )

        embed = discord.Embed(
            title="🛠️ Server Setup Complete",
            description="The Republic of Dravia has been provisioned on this server.",
            color=COLOR_ACCENT,
        )
        embed.add_field(
            name="Roles Created",
            value=", ".join(created_roles) if created_roles else "All roles already exist",
            inline=False,
        )
        embed.add_field(
            name="Channels Created",
            value=", ".join(created_channels) if created_channels else "All channels already exist",
            inline=False,
        )
        embed.add_field(
            name="Next Steps",
            value="1. Assign roles per the Permissions Matrix\n2. Run `/help` to see all commands\n3. `/status` for system health",
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | Ministry of Administration")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="pay", description="Pay a citizen from the Treasury (Admin)")
    @app_commands.describe(user="Recipient", amount="Amount", reason="Reason")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_pay(self, interaction: discord.Interaction, user: discord.User, amount: int, reason: str = "Treasury payment"):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        await self.db.create_user(str(user.id))
        await self.db.add_balance(str(user.id), amount, "treasury", reason)
        admin_log.info("Treasury payment: %s -> %s amount=%s reason=%s", interaction.user.id, user.id, amount, reason)
        embed = discord.Embed(
            title="💰 Treasury Payment",
            description=f"{user.mention} received 🪙 **{amount:,}**",
            color=COLOR_GOLD,
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Authorised by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="set_balance", description="Set a citizen's balance (Admin)")
    @app_commands.describe(user="Citizen", amount="New balance")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_set_balance(self, interaction: discord.Interaction, user: discord.User, amount: int):
        if amount < 0:
            await interaction.response.send_message("❌ Balance cannot be negative.", ephemeral=True)
            return
        await self.db.create_user(str(user.id))
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amount, str(user.id)))
            await db.commit()
        admin_log.info("Balance set: %s -> %s by %s", user.id, amount, interaction.user.id)
        await interaction.response.send_message(
            f"✅ {user.mention}'s balance set to 🪙 **{amount:,}**.", ephemeral=True
        )

    @admin_group.command(name="log", description="View recent admin actions (Admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_log_view(self, interaction: discord.Interaction):
        lines = []
        try:
            with open(os.path.join("logs", "admin.log"), "r", encoding="utf-8") as f:
                lines = f.readlines()[-8:]
        except FileNotFoundError:
            lines = []
        embed = discord.Embed(title="🗂️ Recent Admin Actions", color=COLOR_ACCENT)
        embed.description = "```\n" + ("".join(lines) or "No admin actions logged yet.")[-1500:] + "\n```"
        embed.set_footer(text="Republic of Dravia | admin.log")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="roles", description="Show the Permissions Matrix (Admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_roles(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🔐 Permissions Matrix", color=COLOR_GOLD)
        embed.add_field(
            name="Open to @everyone",
            value="Economy, grants, housing applications, consumer complaints",
            inline=False,
        )
        embed.add_field(
            name="Role-gated commands",
            value=(
                "`@Citizen` voting, UBI claims\n"
                "`@Police Officer` police commands\n"
                "`@Sergeant+` supervisor commands\n"
                "`@Bank Staff` loan approval\n"
                "`@Revenue Staff` tax enforcement\n"
                "`@SEC` investigations\n"
                "`@Consumer Protection` consumer authority\n"
                "`@Curial` curia & audit commands\n"
                "`@Minister` departmental commands\n"
                "`@Admin` full system access"
            ),
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | /setup creates these roles")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
