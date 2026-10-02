"""Dravia State Bot - Events & Festivals"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.logger import tx_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

EVENT_TYPES = ["National Festival", "Cultural Festival", "Community Event", "Economic Event", "Sporting Event"]

SPONSORSHIP = {
    "bronze": 500,
    "silver": 1000,
    "gold": 2500,
    "platinum": 5000,
}

VENDOR_FEES = {"food": 100, "crafts": 75, "general": 50, "premium": 200}

FUNDING_RANGE = (1000, 10000)
TICKET_RANGE = (25, 150)

class Events(commands.Cog):
    """Events and festivals commands."""
    
    event_group = app_commands.Group(name="event", description="Events and festivals")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    async def get_event(self, event_id: int):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM events WHERE id = ?", (event_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    @event_group.command(name="propose", description="Propose a new event")
    @app_commands.describe(name="Event name", date="Date (YYYY-MM-DD)", location="Location")
    @app_commands.choices(event_type=[app_commands.Choice(name=t, value=t) for t in EVENT_TYPES])
    async def event_propose(
        self, interaction: discord.Interaction, name: str, event_type: str, date: str, location: str = "Dravia City"
    ):
        user_id = str(interaction.user.id)
        try:
            event_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            await interaction.response.send_message("❌ Use the format **YYYY-MM-DD**.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO events (name, event_type, organizer_id, date, location, ticket_price, funding, status) VALUES (?, ?, ?, ?, ?, 0, 0, 'proposed')",
                (name, event_type, user_id, event_date.isoformat(), location),
            )
            event_id = cursor.lastrowid
            await db.commit()

        embed = discord.Embed(
            title="🎉 Event Proposed",
            description=f"**{name}** ({event_type})",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Date", value=f"<t:{int(event_date.timestamp())}:D>", inline=True)
        embed.add_field(name="Location", value=location, inline=True)
        embed.add_field(name="Event ID", value=f"**{event_id}**", inline=True)
        embed.add_field(
            name="Available Support",
            value=f"Government grants 🪙 {FUNDING_RANGE[0]:,}–{FUNDING_RANGE[1]:,}\nTickets 🪙 {TICKET_RANGE[0]}–{TICKET_RANGE[1]}",
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | Events Board review within 7 days")
        await interaction.response.send_message(embed=embed)

    @event_group.command(name="list", description="View upcoming events")
    async def event_list(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM events WHERE status != 'cancelled' ORDER BY date ASC LIMIT 10"
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title="🎉 Upcoming Events", color=COLOR_GOLD)
        if not rows:
            embed.description = "No events scheduled. Propose one with `/event propose`!"
        else:
            for r in rows:
                embed.add_field(
                    name=f"#{r['id']} {r['name']}",
                    value=f"{r['event_type']} | <t:{int(datetime.fromisoformat(r['date']).timestamp())}:D> | {r['status']}",
                    inline=False,
                )
        embed.set_footer(text="Republic of Dravia | Events Board")
        await interaction.response.send_message(embed=embed)

    @event_group.command(name="calendar", description="View the annual event calendar")
    async def event_calendar(self, interaction: discord.Interaction):
        year = datetime.now().year
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM events WHERE date LIKE ? ORDER BY date ASC", (f"{year}-%",)
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title=f"📅 {year} Dravian Event Calendar", color=COLOR_ACCENT)
        if not rows:
            embed.description = "No events on the calendar this year."
        else:
            for r in rows:
                embed.add_field(
                    name=f"<t:{int(datetime.fromisoformat(r['date']).timestamp())}:D>",
                    value=f"**{r['name']}** — {r['event_type']}",
                    inline=False,
                )
        embed.set_footer(text="Republic of Dravia | Events Board")
        await interaction.response.send_message(embed=embed)

    @event_group.command(name="register", description="Register to attend an event")
    @app_commands.describe(event_id="Event ID", tickets="Number of tickets")
    async def event_register(self, interaction: discord.Interaction, event_id: int, tickets: int = 1):
        user_id = str(interaction.user.id)
        event = await self.get_event(event_id)
        if not event:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
        if tickets <= 0:
            await interaction.response.send_message("❌ Tickets must be positive.", ephemeral=True)
            return

        ticket_price = max(TICKET_RANGE[0], min(TICKET_RANGE[1], event["ticket_price"] or TICKET_RANGE[0]))
        total = ticket_price * tickets
        balance = await self.db.get_balance(user_id)
        if balance < total:
            await interaction.response.send_message(
                f"❌ {tickets} ticket(s) cost 🪙 {total:,}. You have 🪙 {balance:,}.", ephemeral=True
            )
            return

        await self.db.remove_balance(user_id, total, "event_ticket", f"Tickets for {event['name']}")
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO event_registrations (event_id, user_id, kind, amount) VALUES (?, ?, 'attendee', ?)",
                (event_id, user_id, total),
            )
            await db.commit()

        tx_log.info("Event registration: user=%s event=%s tickets=%s total=%s", user_id, event_id, tickets, total)
        embed = discord.Embed(
            title="🎟️ Registered",
            description=f"**{tickets}** ticket(s) for **{event['name']}**",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Total Paid", value=f"🪙 **{total:,}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @event_group.command(name="sponsor", description="Sponsor an event")
    @app_commands.describe(event_id="Event ID")
    @app_commands.choices(level=[
            app_commands.Choice(name="Bronze (🪙500)", value="bronze"),
            app_commands.Choice(name="Silver (🪙1,000)", value="silver"),
            app_commands.Choice(name="Gold (🪙2,500)", value="gold"),
            app_commands.Choice(name="Platinum (🪙5,000)", value="platinum"),
        ])
    async def event_sponsor(self, interaction: discord.Interaction, event_id: int, level: str):
        user_id = str(interaction.user.id)
        event = await self.get_event(event_id)
        if not event:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return

        amount = SPONSORSHIP[level]
        balance = await self.db.get_balance(user_id)
        if balance < amount:
            await interaction.response.send_message(
                f"❌ {level.title()} sponsorship costs 🪙 {amount:,}.", ephemeral=True
            )
            return

        await self.db.remove_balance(user_id, amount, "sponsorship", f"{level.title()} sponsorship: {event['name']}")
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO event_registrations (event_id, user_id, kind, amount) VALUES (?, ?, 'sponsor', ?)",
                (event_id, user_id, amount),
            )
            await db.execute("UPDATE events SET funding = funding + ? WHERE id = ?", (amount, event_id))
            await db.commit()

        embed = discord.Embed(
            title=f"🏅 {level.title()} Sponsor",
            description=f"{interaction.user.mention} sponsors **{event['name']}**",
            color=COLOR_GOLD,
        )
        embed.add_field(name="Amount", value=f"🪙 **{amount:,}**", inline=True)
        embed.set_footer(text="Republic of Dravia | Events Board")
        await interaction.response.send_message(embed=embed)

    @event_group.command(name="vendor", description="Apply as a vendor at an event")
    @app_commands.describe(event_id="Event ID")
    @app_commands.choices(vendor_type=[app_commands.Choice(name=f"{k.title()} (🪙{v})", value=k) for k, v in VENDOR_FEES.items()])
    async def event_vendor(self, interaction: discord.Interaction, event_id: int, vendor_type: str = "general"):
        user_id = str(interaction.user.id)
        event = await self.get_event(event_id)
        if not event:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return

        fee = VENDOR_FEES.get(vendor_type, 50)
        balance = await self.db.get_balance(user_id)
        if balance < fee:
            await interaction.response.send_message(f"❌ Vendor fee is 🪙 {fee}.", ephemeral=True)
            return

        await self.db.remove_balance(user_id, fee, "vendor_fee", f"Vendor stall: {event['name']}")
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO event_registrations (event_id, user_id, kind, amount) VALUES (?, ?, 'vendor', ?)",
                (event_id, user_id, fee),
            )
            await db.commit()

        embed = discord.Embed(
            title="🛒 Vendor Application Approved",
            description=f"Stall secured at **{event['name']}** ({vendor_type.title()})",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Fee Paid", value=f"🪙 **{fee:,}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @event_group.command(name="report", description="File a post-event report")
    @app_commands.describe(event_id="Event ID", attendance="Total attendance", notes="Notes")
    async def event_report(self, interaction: discord.Interaction, event_id: int, attendance: int, notes: str = ""):
        user_id = str(interaction.user.id)
        event = await self.get_event(event_id)
        if not event:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
        if event["organizer_id"] != user_id:
            await interaction.response.send_message("❌ Only the organiser can file the report.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            await db.execute("UPDATE events SET status = 'completed' WHERE id = ?", (event_id,))
            await db.commit()

        embed = discord.Embed(
            title="📄 Post-Event Report Filed",
            description=f"**{event['name']}** — marked completed",
            color=COLOR_GOLD,
        )
        embed.add_field(name="Attendance", value=f"**{attendance:,}**", inline=True)
        embed.add_field(name="Funding Raised", value=f"🪙 **{event['funding']:,}**", inline=True)
        if notes:
            embed.add_field(name="Notes", value=notes[:1000], inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Events(bot))
