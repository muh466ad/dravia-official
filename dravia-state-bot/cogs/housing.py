"""Dravia State Bot - Housing System"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.logger import tx_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

RENTAL_FEE = 500
APPLICATION_FEE = 50
GUEST_FEE = 100
MAX_GUESTS = 3
ROLE_HOMEOWNER = "Homeowner"

class Housing(commands.Cog):
    """Housing commands for Dravia."""
    
    house_group = app_commands.Group(name="house", description="State housing commands")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    async def get_house(self, user_id: str):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM houses WHERE owner_id = ? AND is_active = 1", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    @house_group.command(name="apply", description="Apply for a state house")
    @app_commands.describe(house_name="Name for your house")
    async def house_apply(self, interaction: discord.Interaction, house_name: str):
        user_id = str(interaction.user.id)

        if await self.get_house(user_id):
            await interaction.response.send_message("⚠️ You already own a house. Use `/house info`.", ephemeral=True)
            return

        balance = await self.db.get_balance(user_id)
        total_fee = APPLICATION_FEE  # application fee only; first rent on /house renew
        if balance < total_fee:
            await interaction.response.send_message(
                f"❌ Application fee is 🪙 {APPLICATION_FEE}. You have 🪙 {balance:,}.",
                ephemeral=True,
            )
            return

        await self.db.remove_balance(user_id, total_fee, "house_application", "House application fee")
        rental_due = (datetime.now() + timedelta(days=30)).isoformat()

        channel = None
        try:
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.guild.get_member(int(user_id)): discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_channels=True
                ),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }
            role = discord.utils.get(interaction.guild.roles, name=ROLE_HOMEOWNER)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True)
            channel = await interaction.guild.create_text_channel(
                name=f"house-{house_name.lower().replace(' ', '-')[:20]}",
                overwrites=overwrites,
                reason=f"House created for {interaction.user.display_name}",
            )
        except Exception:
            channel = None

        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO houses (owner_id, house_name, channel_id, guests, rental_due, last_activity, is_active) VALUES (?, ?, ?, '', ?, ?, 1)",
                (user_id, house_name, str(channel.id) if channel else None, rental_due, datetime.now().isoformat()),
            )
            await db.commit()

        # Grant Homeowner role if present
        try:
            role = discord.utils.get(interaction.guild.roles, name=ROLE_HOMEOWNER)
            if role and isinstance(interaction.user, discord.Member):
                await interaction.user.add_roles(role, reason="Homeowner")
        except Exception:
            pass

        tx_log.info("House '%s' applied by %s", house_name, user_id)
        embed = discord.Embed(
            title="🏠 House Application Approved",
            description=f"Welcome home, {interaction.user.mention}!",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="House", value=f"**{house_name}**", inline=True)
        embed.add_field(name="Application Fee", value=f"🪙 **{APPLICATION_FEE}**", inline=True)
        embed.add_field(name="Monthly Rent", value=f"🪙 **{RENTAL_FEE}**", inline=True)
        embed.add_field(name="First Rent Due", value=f"<t:{int((datetime.now() + timedelta(days=30)).timestamp())}:D>", inline=True)
        if channel:
            embed.add_field(name="Private Channel", value=channel.mention, inline=True)
        embed.set_footer(text="Republic of Dravia | Housing Authority")
        await interaction.response.send_message(embed=embed)

    @house_group.command(name="invite", description="Invite a guest to your house")
    @app_commands.describe(user="Guest to invite")
    async def house_invite(self, interaction: discord.Interaction, user: discord.Member):
        user_id = str(interaction.user.id)
        house = await self.get_house(user_id)
        if not house:
            await interaction.response.send_message("❌ You don't own a house.", ephemeral=True)
            return

        guests = [g for g in (house["guests"] or "").split(",") if g]
        if str(user.id) in guests:
            await interaction.response.send_message("⚠️ That user is already a guest.", ephemeral=True)
            return
        if len(guests) >= MAX_GUESTS:
            await interaction.response.send_message(f"❌ Maximum {MAX_GUESTS} guests per house.", ephemeral=True)
            return

        balance = await self.db.get_balance(user_id)
        if balance < GUEST_FEE:
            await interaction.response.send_message(f"❌ Guest fee is 🪙 {GUEST_FEE}.", ephemeral=True)
            return

        await self.db.remove_balance(user_id, GUEST_FEE, "guest_fee", "House guest fee")
        guests.append(str(user.id))

        # Give guest channel access
        try:
            channel = None
            if house["channel_id"]:
                channel = interaction.guild.get_channel(int(house["channel_id"]))
            if channel:
                await channel.set_permissions(user, view_channel=True, send_messages=True)
        except Exception:
            pass

        async with await self.db.get_connection() as db:
            await db.execute("UPDATE houses SET guests = ? WHERE id = ?", (",".join(guests), house["id"]))
            await db.commit()

        embed = discord.Embed(
            title="🔑 Guest Invited",
            description=f"{user.mention} is now a guest of **{house['house_name']}**",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Guests", value=f"{len(guests)}/{MAX_GUESTS}", inline=True)
        embed.add_field(name="Fee", value=f"🪙 **{GUEST_FEE}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @house_group.command(name="remove", description="Remove a guest from your house")
    @app_commands.describe(user="Guest to remove")
    async def house_remove(self, interaction: discord.Interaction, user: discord.Member):
        user_id = str(interaction.user.id)
        house = await self.get_house(user_id)
        if not house:
            await interaction.response.send_message("❌ You don't own a house.", ephemeral=True)
            return

        guests = [g for g in (house["guests"] or "").split(",") if g]
        if str(user.id) not in guests:
            await interaction.response.send_message("❌ That user is not a guest.", ephemeral=True)
            return

        guests.remove(str(user.id))
        try:
            if house["channel_id"]:
                channel = interaction.guild.get_channel(int(house["channel_id"]))
                if channel:
                    await channel.set_permissions(user, overwrite=None)
        except Exception:
            pass

        async with await self.db.get_connection() as db:
            await db.execute("UPDATE houses SET guests = ? WHERE id = ?", (",".join(guests), house["id"]))
            await db.commit()

        await interaction.response.send_message(f"🚪 {user.mention} removed from **{house['house_name']}**.", ephemeral=True)

    @house_group.command(name="renew", description="Pay your monthly rent")
    async def house_renew(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        house = await self.get_house(user_id)
        if not house:
            await interaction.response.send_message("❌ You don't own a house.", ephemeral=True)
            return

        balance = await self.db.get_balance(user_id)
        if balance < RENTAL_FEE:
            await interaction.response.send_message(
                f"❌ Rent is 🪙 {RENTAL_FEE}/month. You have 🪙 {balance:,}. Rent unpaid for 7 days = repossession.",
                ephemeral=True,
            )
            return

        await self.db.remove_balance(user_id, RENTAL_FEE, "rent", "Monthly house rent")
        new_due = (datetime.now() + timedelta(days=30)).isoformat()
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE houses SET rental_due = ?, last_activity = ? WHERE id = ?",
                (new_due, datetime.now().isoformat(), house["id"]),
            )
            await db.commit()

        tx_log.info("Rent paid: house=%s user=%s", house["id"], user_id)
        embed = discord.Embed(title="🏠 Rent Paid", color=COLOR_GOLD)
        embed.add_field(name="Amount", value=f"🪙 **{RENTAL_FEE}**", inline=True)
        embed.add_field(name="Next Due", value=f"<t:{int((datetime.now() + timedelta(days=30)).timestamp())}:D>", inline=True)
        await interaction.response.send_message(embed=embed)

    @house_group.command(name="cancel", description="Cancel your house rental")
    async def house_cancel(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        house = await self.get_house(user_id)
        if not house:
            await interaction.response.send_message("❌ You don't own a house.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            await db.execute("UPDATE houses SET is_active = 0 WHERE id = ?", (house["id"],))
            await db.commit()

        # Delete the private channel if possible
        try:
            if house["channel_id"]:
                channel = interaction.guild.get_channel(int(house["channel_id"]))
                if channel:
                    await channel.delete(reason="House rental cancelled")
        except Exception:
            pass

        try:
            role = discord.utils.get(interaction.guild.roles, name=ROLE_HOMEOWNER)
            if role and isinstance(interaction.user, discord.Member):
                await interaction.user.remove_roles(role, reason="House cancelled")
        except Exception:
            pass

        await interaction.response.send_message(
            f"🏠 Rental of **{house['house_name']}** cancelled. The channel has been closed.",
            ephemeral=True,
        )

    @house_group.command(name="info", description="View your house details")
    async def house_info(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        house = await self.get_house(user_id)
        if not house:
            embed = discord.Embed(
                title="🏠 No House",
                description="You don't own a house. Use `/house apply` to apply!",
                color=COLOR_CRIMSON,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        guests = [g for g in (house["guests"] or "").split(",") if g]
        due = datetime.fromisoformat(house["rental_due"])
        days_left = (due - datetime.now()).days

        embed = discord.Embed(title=f"🏠 {house['house_name']}", color=COLOR_ACCENT)
        embed.add_field(name="Owner", value=f"<@{house['owner_id']}>", inline=True)
        embed.add_field(name="Rent Due", value=f"<t:{int(due.timestamp())}:D>", inline=True)
        embed.add_field(name="Days Left", value=f"**{days_left}**", inline=True)
        embed.add_field(name="Guests", value=f"**{len(guests)}/{MAX_GUESTS}**", inline=True)
        if house["channel_id"]:
            embed.add_field(name="Channel", value=f"<#{house['channel_id']}>", inline=True)
        embed.add_field(name="Rent", value=f"🪙 **{RENTAL_FEE}**/month", inline=True)
        embed.set_footer(text="Republic of Dravia | Unauthorized entry is an offence")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Housing(bot))
