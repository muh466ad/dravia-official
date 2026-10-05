"""Dravia State Bot - Police System"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.calendar import stamp
from utils.checks import requires_police, requires_supervisor
from utils.logger import police_log, audit_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

POLICE_RANKS = [
    "Recruit", "Officer", "Senior Officer", "Sergeant", "Inspector",
    "Chief Inspector", "Superintendent", "Deputy Chief", "Commissioner"
]

CRIMES = {
    "theft": {"name": "Theft", "fine": 5000, "jail": 7},
    "fraud": {"name": "Fraud", "fine": 15000, "jail": 14},
    "assault": {"name": "Assault", "fine": 8000, "jail": 10},
    "vandalism": {"name": "Vandalism", "fine": 2000, "jail": 3},
    "tax_evasion": {"name": "Tax Evasion", "fine": 25000, "jail": 21},
    "bribery": {"name": "Bribery", "fine": 20000, "jail": 14},
    "impersonation": {"name": "Impersonation", "fine": 10000, "jail": 7},
    "smuggling": {"name": "Smuggling", "fine": 30000, "jail": 30}
}

class Police(commands.Cog):
    """Police commands for Dravia."""
    
    police_group = app_commands.Group(name="police", description="Dravia Police operational commands")
    ia_group = app_commands.Group(name="ia", description="Internal Affairs commands")
    ipoc_group = app_commands.Group(name="ipoc", description="Independent Police Oversight Commission")
    
    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)
    
    async def get_police_record(self, user_id: str) -> dict:
        """Get police record."""
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM police WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def is_police(self, user_id: str) -> bool:
        """Check if user is police."""
        record = await self.get_police_record(user_id)
        return record is not None and record.get("rank") is not None
    
    # (Police help stub replaced by the /police command group)
    
    @police_group.command(name="join", description="Join the Dravia Police Force")
    async def join_police(self, interaction: discord.Interaction):
        """Join police force."""
        user_id = str(interaction.user.id)
        
        existing = await self.get_police_record(user_id)
        if existing and existing.get("rank"):
            await interaction.response.send_message(
                "⚠️ You are already in the Police Force!",
                ephemeral=True
            )
            return
        
        # Create record
        async with await self.db.get_connection() as db:
            await db.execute(
                """INSERT OR REPLACE INTO police (user_id, rank, join_date, status, arrests)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, "Recruit", datetime.now().isoformat(), "active", 0)
            )
            await db.commit()
        
        embed = discord.Embed(
            title="✅ Welcome to the Police!",
            description="You have joined the Dravia Police Force as a **Recruit**",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Rank", value="Recruit", inline=True)
        embed.add_field(name="Status", value="Active", inline=True)
        embed.set_footer(text="Dravia Police Academy")
        
        await interaction.response.send_message(embed=embed)
    
    @police_group.command(name="record", description="Check someone's criminal record")
    @app_commands.describe(user="User to check")
    async def check_record(self, interaction: discord.Interaction, user: discord.User):
        """Check criminal record."""
        user_id = str(user.id)
        
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            
            # Get criminal record
            async with db.execute(
                "SELECT * FROM criminals WHERE discord_id = ?", (user_id,)
            ) as cursor:
                criminal = await cursor.fetchone()
            
            # Get police record
            async with db.execute(
                "SELECT * FROM police WHERE user_id = ?", (user_id,)
            ) as cursor:
                police = await cursor.fetchone()
        
        embed = discord.Embed(
            title=f"🔍 Record for {user.display_name}",
            color=COLOR_CRIMSON if criminal else COLOR_ACCENT
        )
        
        # Criminal record
        if criminal:
            embed.add_field(
                name="⚠️ Criminal Record",
                value=f"**Offenses:** {criminal['offense_count']}\n**Fines Due:** 🪙 {criminal['fines_due']:,}\n**Jail Time:** {criminal['jail_days']} days",
                inline=False
            )
        else:
            embed.add_field(
                name="✅ Clean Record",
                value="No criminal history",
                inline=False
            )
        
        # Police status
        if police and police.get("rank"):
            embed.add_field(
                name="👮 Police Status",
                value=f"**Rank:** {police['rank']}\n**Arrests:** {police['arrests']}",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @police_group.command(name="wanted", description="List wanted criminals")
    async def wanted_list(self, interaction: discord.Interaction):
        """List wanted criminals."""
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM criminals WHERE fines_due > 0 ORDER BY fines_due DESC LIMIT 10"
            ) as cursor:
                criminals = await cursor.fetchall()
        
        if not criminals:
            embed = discord.Embed(
                title="✅ No Wanted Criminals",
                description="Dravia is safe!",
                color=COLOR_ACCENT
            )
            await interaction.response.send_message(embed=embed)
            return
        
        embed = discord.Embed(
            title="🔴 Wanted List",
            description="Criminals with outstanding fines",
            color=COLOR_CRIMSON
        )
        
        for c in criminals:
            embed.add_field(
                name=f"User {c['discord_id'][:8]}...",
                value=f"Offenses: {c['offense_count']} | Fines: 🪙 {c['fines_due']:,}",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="arrest", description="Arrest a criminal (Police only)")
    @app_commands.describe(
        user="Criminal to arrest",
        crime="Crime committed"
    )
    @app_commands.choices(crime=[
        app_commands.Choice(name="Theft (5000 fine, 7 days jail)", value="theft"),
        app_commands.Choice(name="Fraud (15000 fine, 14 days jail)", value="fraud"),
        app_commands.Choice(name="Assault (8000 fine, 10 days jail)", value="assault"),
        app_commands.Choice(name="Vandalism (2000 fine, 3 days jail)", value="vandalism"),
        app_commands.Choice(name="Tax Evasion (25000 fine, 21 days jail)", value="tax_evasion"),
        app_commands.Choice(name="Bribery (20000 fine, 14 days jail)", value="bribery"),
        app_commands.Choice(name="Impersonation (10000 fine, 7 days jail)", value="impersonation"),
        app_commands.Choice(name="Smuggling (30000 fine, 30 days jail)", value="smuggling")
    ])
    async def arrest(self, interaction: discord.Interaction, user: discord.User, crime: str):
        """Arrest a criminal."""
        police_id = str(interaction.user.id)
        
        if not await self.is_police(police_id):
            await interaction.response.send_message(
                "❌ Only police officers can make arrests!",
                ephemeral=True
            )
            return
        
        criminal_id = str(user.id)
        crime_data = CRIMES[crime]
        
        # Add criminal record
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM criminals WHERE discord_id = ?", (criminal_id,)
            ) as cursor:
                existing = await cursor.fetchone()
            
            if existing:
                await db.execute(
                    """UPDATE criminals SET 
                       offense_count = offense_count + 1,
                       fines_due = fines_due + ?,
                       jail_days = jail_days + ?,
                       last_arrest = ?
                       WHERE discord_id = ?""",
                    (crime_data["fine"], crime_data["jail"], datetime.now().isoformat(), criminal_id)
                )
            else:
                await db.execute(
                    """INSERT INTO criminals (discord_id, offense_count, fines_due, jail_days, last_arrest)
                       VALUES (?, ?, ?, ?, ?)""",
                    (criminal_id, 1, crime_data["fine"], crime_data["jail"], datetime.now().isoformat())
                )
            
            # Update police arrest count
            await db.execute(
                "UPDATE police SET arrests = arrests + 1 WHERE user_id = ?",
                (police_id,)
            )
            
            await db.commit()
        
        # Fine from user if they can pay
        balance = await self.db.get_balance(criminal_id)
        if balance >= crime_data["fine"]:
            await self.db.remove_balance(criminal_id, crime_data["fine"], "fine", f"{crime} fine")
        
        embed = discord.Embed(
            title="✅ Arrest Successful",
            description=f"**{user.display_name}** arrested for **{crime_data['name']}**",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Fine", value=f"🪙 **{crime_data['fine']:,}**", inline=True)
        embed.add_field(name="Jail Time", value=f"**{crime_data['jail']} days**", inline=True)
        embed.add_field(name="Officer", value=interaction.user.display_name, inline=True)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="pay_fine", description="Pay your outstanding fines")
    @app_commands.describe(amount="Amount to pay (leave empty for full amount)")
    async def pay_fine(self, interaction: discord.Interaction, amount: int = None):
        """Pay fines."""
        user_id = str(interaction.user.id)
        
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT fines_due FROM criminals WHERE discord_id = ?", (user_id,)
            ) as cursor:
                record = await cursor.fetchone()
        
        if not record or record["fines_due"] <= 0:
            await interaction.response.send_message(
                "✅ You have no outstanding fines!",
                ephemeral=True
            )
            return
        
        fines_due = record["fines_due"]
        
        if amount is None:
            amount = fines_due
        
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        
        balance = await self.db.get_balance(user_id)
        if balance < amount:
            await interaction.response.send_message(
                f"❌ Insufficient funds. You have {balance:,} Ovi.",
                ephemeral=True
            )
            return
        
        # Pay fine
        await self.db.remove_balance(user_id, amount, "fine_payment", "Criminal fine")
        
        new_fines = max(0, fines_due - amount)
        
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE criminals SET fines_due = ? WHERE discord_id = ?",
                (new_fines, user_id)
            )
            await db.commit()
        
        embed = discord.Embed(
            title="✅ Fine Paid",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Amount Paid", value=f"🪙 **{amount:,}**", inline=True)
        embed.add_field(name="Remaining", value=f"🪙 **{new_fines:,}**", inline=True)
        
        await interaction.response.send_message(embed=embed)


    # --- Duty ---

    @police_group.command(name="duty_start", description="Begin your shift (Police only)")
    @requires_police
    async def police_duty_start(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO duty_sessions (user_id, started_at) VALUES (?, ?)",
                (user_id, datetime.now().isoformat()),
            )
            await db.commit()
        police_log.info("Duty started: %s", user_id)
        embed = discord.Embed(
            title="🚔 Duty Started",
            description="You are now **10-8 In Service**.",
            color=COLOR_ACCENT,
        )
        embed.set_footer(text="End shift with /police duty_end")
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="duty_end", description="End your shift (Police only)")
    @requires_police
    async def police_duty_end(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        elapsed = None
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, started_at FROM duty_sessions WHERE user_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
                (user_id,),
            ) as cursor:
                session = await cursor.fetchone()
            if session:
                await db.execute(
                    "UPDATE duty_sessions SET ended_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), session["id"]),
                )
                elapsed = datetime.now() - datetime.fromisoformat(session["started_at"])
            await db.commit()

        police_log.info("Duty ended: %s", user_id)
        embed = discord.Embed(title="🏠 Duty Ended", color=COLOR_GOLD)
        if elapsed:
            minutes = int(elapsed.total_seconds() // 60)
            embed.add_field(name="Shift Length", value=f"**{minutes} minutes**", inline=True)
        embed.set_footer(text="Thank you for your service. 10-7 Out of Service.")
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="status", description="View duty status")
    async def police_status(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        record = await self.get_police_record(user_id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM duty_sessions WHERE user_id = ? AND ended_at IS NULL", (user_id,)
            ) as cursor:
                on_duty = (await cursor.fetchone())[0] > 0
            async with db.execute(
                "SELECT COUNT(*) FROM duty_sessions WHERE user_id = ?", (user_id,)
            ) as cursor:
                shifts = (await cursor.fetchone())[0]

        embed = discord.Embed(title="🚔 Duty Status", color=COLOR_ACCENT)
        embed.add_field(name="Status", value="**10-8 In Service**" if on_duty else "**10-7 Out of Service**", inline=True)
        embed.add_field(name="Rank", value=record["rank"] if record else "Civilian", inline=True)
        embed.add_field(name="Total Shifts", value=f"**{shifts}**", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Miranda, cuffs, search, jail ---

    @police_group.command(name="miranda", description="Read a suspect their rights")
    @app_commands.describe(user="Suspect")
    @requires_police
    async def police_miranda(self, interaction: discord.Interaction, user: discord.User):
        rights = (
            f"{user.mention}, you have the right to remain silent. Anything you say can and will be used "
            "against you in a court of law. You have the right to an attorney. If you cannot afford one, "
            "one will be appointed to you. Do you understand these rights?"
        )
        embed = discord.Embed(title="⚖️ Miranda Rights Read", description=rights, color=COLOR_ACCENT)
        embed.set_footer(text="Republic of Dravia | De Custodia Publica Draviae")
        await interaction.response.send_message(embed=embed)
        police_log.info("Miranda read to %s by %s", user.id, interaction.user.id)

    @police_group.command(name="cuff", description="Handcuff a suspect")
    @app_commands.describe(user="Suspect")
    @requires_police
    async def police_cuff(self, interaction: discord.Interaction, user: discord.User):
        police_log.info("Cuffed %s by %s", user.id, interaction.user.id)
        embed = discord.Embed(
            title="🔗 Suspect Restrained",
            description=f"{user.mention} has been handcuffed.",
            color=COLOR_ACCENT,
        )
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="uncuff", description="Remove handcuffs")
    @app_commands.describe(user="Person")
    @requires_police
    async def police_uncuff(self, interaction: discord.Interaction, user: discord.User):
        police_log.info("Uncuffed %s by %s", user.id, interaction.user.id)
        embed = discord.Embed(
            title="🔓 Released",
            description=f"Handcuffs removed from {user.mention}.",
            color=COLOR_ACCENT,
        )
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="search", description="Search a person")
    @app_commands.describe(user="Person to search")
    @requires_police
    async def police_search(self, interaction: discord.Interaction, user: discord.User):
        balance = await self.db.get_balance(str(user.id))
        police_log.info("Search of %s by %s", user.id, interaction.user.id)
        embed = discord.Embed(title=f"🔍 Search: {user.display_name}", color=COLOR_ACCENT)
        embed.add_field(name="Items Found", value="No contraband seized.", inline=False)
        embed.add_field(name="Cash on Person", value=f"🪙 **{balance:,}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="jail", description="Jail a suspect")
    @app_commands.describe(user="Suspect", days="Sentence in days", reason="Charge")
    @requires_police
    async def police_jail(self, interaction: discord.Interaction, user: discord.User, days: int, reason: str):
        if days <= 0:
            await interaction.response.send_message("❌ Sentence must be positive.", ephemeral=True)
            return
        criminal_id = str(user.id)
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM criminals WHERE discord_id = ?", (criminal_id,)) as cursor:
                existing = await cursor.fetchone()
            if existing:
                await db.execute(
                    "UPDATE criminals SET jail_days = jail_days + ?, offense_count = offense_count + 1, last_arrest = ? WHERE discord_id = ?",
                    (days, datetime.now().isoformat(), criminal_id),
                )
            else:
                await db.execute(
                    "INSERT INTO criminals (discord_id, offense_count, jail_days, last_arrest) VALUES (?, 1, ?, ?)",
                    (criminal_id, days, datetime.now().isoformat()),
                )
            await db.execute(
                """INSERT INTO criminal_records (user_id, charge, severity, fine, jail_days, date, officer_id)
                   VALUES (?, ?, 'standard', 0, ?, ?, ?)""",
                (criminal_id, reason, days, datetime.now().date().isoformat(), str(interaction.user.id)),
            )
            await db.commit()

        police_log.info("Jailed %s for %s days by %s: %s", user.id, days, interaction.user.id, reason)
        embed = discord.Embed(
            title="⛓️ Suspect Jailed",
            description=f"{user.mention} sentenced to **{days} days** for *{reason}*",
            color=COLOR_CRIMSON,
        )
        embed.set_footer(text="Republic of Dravia | Central Detention")
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="release", description="Release a suspect from jail")
    @app_commands.describe(user="Inmate")
    @requires_police
    async def police_release(self, interaction: discord.Interaction, user: discord.User):
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE criminals SET jail_days = 0 WHERE discord_id = ?", (str(user.id),)
            )
            await db.commit()
        police_log.info("Released %s by %s", user.id, interaction.user.id)
        embed = discord.Embed(
            title="🔓 Released",
            description=f"{user.mention} released from custody.",
            color=COLOR_ACCENT,
        )
        await interaction.response.send_message(embed=embed)

    # --- Warrants & BOLOs ---

    @police_group.command(name="warrant_issue", description="Issue an arrest warrant")
    @app_commands.describe(user="Suspect", reason="Probable cause")
    @requires_supervisor
    async def police_warrant_issue(self, interaction: discord.Interaction, user: discord.User, reason: str):
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO warrants (user_id, reason, issued_by, date) VALUES (?, ?, ?, ?)",
                (str(user.id), reason, str(interaction.user.id), datetime.now().date().isoformat()),
            )
            warrant_id = cursor.lastrowid
            await db.commit()
        audit_log.info("Warrant #%s issued for %s by %s: %s", warrant_id, user.id, interaction.user.id, reason)
        embed = discord.Embed(
            title="📜 Warrant Issued",
            description=f"Warrant **#{warrant_id}** for {user.mention}",
            color=COLOR_CRIMSON,
        )
        embed.add_field(name="Probable Cause", value=reason[:1000], inline=False)
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="warrant_serve", description="Serve an active warrant")
    @app_commands.describe(user="Suspect")
    @requires_police
    async def police_warrant_serve(self, interaction: discord.Interaction, user: discord.User):
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE warrants SET status = 'served' WHERE user_id = ? AND status = 'active'",
                (str(user.id),),
            )
            await db.commit()
        audit_log.info("Warrant served on %s by %s", user.id, interaction.user.id)
        embed = discord.Embed(
            title="✅ Warrant Served",
            description=f"All active warrants for {user.mention} executed.",
            color=COLOR_ACCENT,
        )
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="warrant_list", description="View active warrants")
    async def police_warrant_list(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM warrants WHERE status = 'active' ORDER BY warrant_id DESC LIMIT 10"
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title="📜 Active Warrants", color=COLOR_CRIMSON)
        if not rows:
            embed.description = "No active warrants."
        else:
            for r in rows:
                embed.add_field(
                    name=f"#{r['warrant_id']} <@{r['user_id']}>",
                    value=f"{(r['reason'] or '')[:100]} | Issued {r['date']}",
                    inline=False,
                )
        embed.set_footer(text="Republic of Dravia | Warrants Division")
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="bolo_create", description="Issue a BOLO (Be On the Look Out)")
    @app_commands.describe(description="Description of person/vehicle")
    @requires_police
    async def police_bolo_create(self, interaction: discord.Interaction, description: str):
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO bolos (description, issued_by, date) VALUES (?, ?, ?)",
                (description, str(interaction.user.id), datetime.now().date().isoformat()),
            )
            bolo_id = cursor.lastrowid
            await db.commit()
        police_log.info("BOLO #%s issued by %s: %s", bolo_id, interaction.user.id, description)
        embed = discord.Embed(
            title="🚨 BOLO Issued",
            description=f"**#{bolo_id}** — {description[:500]}",
            color=COLOR_CRIMSON,
        )
        embed.set_footer(text="Republic of Dravia | All units notified")
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="bolo_list", description="View active BOLOs")
    async def police_bolo_list(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM bolos WHERE status = 'active' ORDER BY bolo_id DESC LIMIT 10"
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title="🚨 Active BOLOs", color=COLOR_CRIMSON)
        if not rows:
            embed.description = "No active BOLOs."
        else:
            for r in rows:
                embed.add_field(
                    name=f"#{r['bolo_id']}",
                    value=f"{(r['description'] or '')[:200]} | {r['date']}",
                    inline=False,
                )
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="report", description="File an incident report")
    @app_commands.describe(incident="Description of the incident")
    @requires_police
    async def police_report(self, interaction: discord.Interaction, incident: str):
        police_log.info("Incident report by %s: %s", interaction.user.id, incident[:200])
        embed = discord.Embed(
            title="📄 Incident Report Filed",
            description=incident[:1000],
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Reporting Officer", value=interaction.user.mention, inline=True)
        embed.add_field(name="Filed", value=stamp(), inline=True)
        embed.set_footer(text="Republic of Dravia | Records Division")
        await interaction.response.send_message(embed=embed)

    @police_group.command(name="radio", description="Send a 10-code over the radio")
    @app_commands.choices(code=[
        app_commands.Choice(name="10-4 Acknowledged", value="10-4"),
        app_commands.Choice(name="10-7 Out of service", value="10-7"),
        app_commands.Choice(name="10-8 In service", value="10-8"),
        app_commands.Choice(name="10-20 Location", value="10-20"),
        app_commands.Choice(name="10-33 Emergency", value="10-33"),
        app_commands.Choice(name="10-80 Pursuit", value="10-80"),
        app_commands.Choice(name="10-99 Wanted/stolen", value="10-99"),
    ])
    @requires_police
    async def police_radio(self, interaction: discord.Interaction, code: str, message: str = ""):
        meanings = {
            "10-4": "Acknowledged",
            "10-7": "Out of service",
            "10-8": "In service",
            "10-20": "Location",
            "10-33": "EMERGENCY",
            "10-80": "PURSUIT IN PROGRESS",
            "10-99": "WANTED/STOLEN",
        }
        police_log.info("Radio %s from %s: %s", code, interaction.user.id, message)
        embed = discord.Embed(
            title=f"📻 {code} — {meanings.get(code, '')}",
            description=message or "—",
            color=COLOR_CRIMSON if code in ("10-33", "10-80", "10-99") else COLOR_ACCENT,
        )
        embed.set_footer(text=f"Unit: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    # --- Internal Affairs ---

    @ia_group.command(name="complaint", description="File a complaint against an officer")
    @app_commands.describe(officer="Officer complained about", reason="What they did")
    async def ia_complaint(self, interaction: discord.Interaction, officer: discord.User, reason: str):
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO ia_cases (officer_id, complainant_id, reason, opened_at) VALUES (?, ?, ?, ?)",
                (str(officer.id), str(interaction.user.id), reason, datetime.now().isoformat()),
            )
            case_id = cursor.lastrowid
            await db.commit()
        audit_log.info("IA complaint #%s against %s by %s: %s", case_id, officer.id, interaction.user.id, reason)
        embed = discord.Embed(
            title="⚖️ IA Complaint Filed",
            description=f"Case **#{case_id}** opened against {officer.mention}.",
            color=COLOR_CRIMSON,
        )
        embed.add_field(name="Reason", value=reason[:1000], inline=False)
        embed.set_footer(text="Independent Police Oversight Commission notified")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ia_group.command(name="investigate", description="Open an IA investigation")
    @app_commands.describe(case_id="IA case number")
    @requires_supervisor
    async def ia_investigate(self, interaction: discord.Interaction, case_id: int):
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE ia_cases SET status = 'investigating' WHERE case_id = ?", (case_id,))
            await db.commit()
        audit_log.info("IA investigation #%s opened by %s", case_id, interaction.user.id)
        await interaction.response.send_message(f"🔍 IA case **#{case_id}** — investigation opened.", ephemeral=True)

    @ia_group.command(name="findings", description="View IA findings")
    @app_commands.describe(case_id="IA case number")
    async def ia_findings(self, interaction: discord.Interaction, case_id: int):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM ia_cases WHERE case_id = ?", (case_id,)) as cursor:
                case = await cursor.fetchone()
        if not case:
            await interaction.response.send_message("❌ Case not found.", ephemeral=True)
            return

        embed = discord.Embed(title=f"⚖️ IA Case #{case_id}", color=COLOR_ACCENT)
        embed.add_field(name="Officer", value=f"<@{case['officer_id']}>", inline=True)
        embed.add_field(name="Status", value=case["status"].title(), inline=True)
        embed.add_field(name="Reason", value=(case["reason"] or "")[:1000], inline=False)
        if case["findings"]:
            embed.add_field(name="Findings", value=case["findings"][:1000], inline=False)
        if case["penalty"]:
            embed.add_field(name="Penalty", value=case["penalty"], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ia_group.command(name="penalty", description="Apply a penalty to an officer")
    @app_commands.describe(case_id="IA case number", penalty="Penalty to apply")
    @requires_supervisor
    async def ia_penalty(self, interaction: discord.Interaction, case_id: int, penalty: str):
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE ia_cases SET status = 'closed', penalty = ?, closed_at = ? WHERE case_id = ?",
                (penalty, datetime.now().isoformat(), case_id),
            )
            await db.commit()
        audit_log.warning("IA penalty #%s: %s applied by %s", case_id, penalty, interaction.user.id)
        embed = discord.Embed(
            title="⚖️ Penalty Applied",
            description=f"Case **#{case_id}**: {penalty}",
            color=COLOR_CRIMSON,
        )
        embed.set_footer(text="Schedule: minor negligence → termination with DOJ referral")
        await interaction.response.send_message(embed=embed)

    @ia_group.command(name="register", description="Public register of IA violations")
    async def ia_register(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM ia_cases ORDER BY case_id DESC LIMIT 10"
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title="📚 IA Public Register", color=COLOR_GOLD)
        if not rows:
            embed.description = "No complaints on record."
        else:
            for r in rows:
                embed.add_field(
                    name=f"#{r['case_id']} — {r['status'].title()}",
                    value=f"Officer <@{r['officer_id']}> | {(r['reason'] or '')[:100]}",
                    inline=False,
                )
        embed.set_footer(text="Transparency: all IA decisions are public")
        await interaction.response.send_message(embed=embed)

    # --- IPOC (oversight) ---

    @ipoc_group.command(name="review", description="Review an IA decision (IPOC)")
    @app_commands.describe(case_id="IA case number")
    @requires_supervisor
    async def ipoc_review(self, interaction: discord.Interaction, case_id: int):
        audit_log.info("IPOC review of case #%s by %s", case_id, interaction.user.id)
        embed = discord.Embed(
            title="🏛️ IPOC Review",
            description=f"Case **#{case_id}** reviewed by the Independent Police Oversight Commission.",
            color=COLOR_GOLD,
        )
        embed.set_footer(text="IPOC reports annually to the Curia")
        await interaction.response.send_message(embed=embed)

    @ipoc_group.command(name="adopt_or_explain", description="Require an explanation for an IA decision")
    @app_commands.describe(case_id="IA case number")
    @requires_supervisor
    async def ipoc_adopt_or_explain(self, interaction: discord.Interaction, case_id: int):
        audit_log.info("IPOC adopt-or-explain on case #%s by %s", case_id, interaction.user.id)
        embed = discord.Embed(
            title="⚖️ Adopt or Explain",
            description=f"The IA must **adopt its findings or publicly explain** case **#{case_id}** within 14 days.",
            color=COLOR_CRIMSON,
        )
        await interaction.response.send_message(embed=embed)

    @ipoc_group.command(name="investigate", description="Open an independent IPOC investigation")
    @app_commands.describe(case_id="IA case number")
    @requires_supervisor
    async def ipoc_investigate(self, interaction: discord.Interaction, case_id: int):
        audit_log.warning("IPOC independent investigation #%s opened by %s", case_id, interaction.user.id)
        embed = discord.Embed(
            title="🔍 IPOC Investigation Opened",
            description=f"Independent investigation into case **#{case_id}**.",
            color=COLOR_CRIMSON,
        )
        embed.set_footer(text="IPOC has independent investigative authority")
        await interaction.response.send_message(embed=embed)

    @ipoc_group.command(name="report", description="Annual IPOC report to the Curia")
    @requires_supervisor
    async def ipoc_report(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT COUNT(*) FROM ia_cases") as cursor:
                total = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM ia_cases WHERE status = 'closed'") as cursor:
                closed = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM police") as cursor:
                officers = (await cursor.fetchone())[0]

        embed = discord.Embed(title="🏛️ IPOC Annual Report", color=COLOR_GOLD)
        embed.add_field(name="Officers Oversighted", value=f"**{officers}**", inline=True)
        embed.add_field(name="Complaints Received", value=f"**{total}**", inline=True)
        embed.add_field(name="Cases Closed", value=f"**{closed}**", inline=True)
        embed.add_field(name="Open Cases", value=f"**{total - closed}**", inline=True)
        embed.set_footer(text="Submitted to the Curia Draviae")
        await interaction.response.send_message(embed=embed)
        audit_log.info("IPOC annual report published by %s", interaction.user.id)

    @ipoc_group.command(name="mediation", description="Mediate a minor complaint")
    @app_commands.describe(case_id="IA case number")
    @requires_supervisor
    async def ipoc_mediation(self, interaction: discord.Interaction, case_id: int):
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE ia_cases SET status = 'mediation' WHERE case_id = ?", (case_id,)
            )
            await db.commit()
        embed = discord.Embed(
            title="🤝 Mediation Offered",
            description=f"Case **#{case_id}** referred to mediation — a minor complaint may be resolved without formal action.",
            color=COLOR_ACCENT,
        )
        await interaction.response.send_message(embed=embed)


    bounty_group = app_commands.Group(name="bounty", description="The bounty board")

    @bounty_group.command(name="post", description="Put a bounty on a wanted citizen")
    @app_commands.describe(target="Who the bounty is on", amount="Reward in Ovi",
                           reason="Why they are wanted")
    async def bounty_post(self, interaction: discord.Interaction, target: discord.Member,
                          amount: int, reason: str):
        if target.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ You cannot post a bounty on yourself.", ephemeral=True)
            return
        if amount < 100:
            await interaction.response.send_message(
                "❌ Bounties start at 100 Ovi.", ephemeral=True)
            return
        reason = " ".join(reason.split())[:120]
        if not reason:
            await interaction.response.send_message(
                "❌ Give a reason for the bounty.", ephemeral=True)
            return
        poster_id = str(interaction.user.id)
        if await self.db.get_balance(poster_id) < amount:
            await interaction.response.send_message(
                f"❌ A bounty of {amount:,} Ovi exceeds your balance.", ephemeral=True)
            return
        await self.db.remove_balance(poster_id, amount, "bounty",
                                     f"Bounty on {target.id}")
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO bounties (target_id, placed_by, amount, reason, status, created_at) "
                "VALUES (?, ?, ?, ?, 'active', date('now'))",
                (str(target.id), poster_id, amount, reason),
            )
            bounty_id = cursor.lastrowid
            await db.commit()
        audit_log.info("Bounty %s posted on %s by %s amount=%s",
                       bounty_id, target.id, poster_id, amount)
        embed = discord.Embed(
            title="💰 Bounty Posted",
            description=f"**{amount:,} Ovi** for the capture of **{target.display_name}**.",
            color=COLOR_CRIMSON,
        )
        embed.add_field(name="Bounty ID", value=f"#{bounty_id}", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text="Republic of Dravia | /bounty claim to collect")
        await interaction.response.send_message(embed=embed)

    @bounty_group.command(name="list", description="Active bounties")
    async def bounty_list(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT bounty_id, target_id, placed_by, amount, reason FROM bounties "
                "WHERE status = 'active' ORDER BY amount DESC LIMIT 15"
            ) as cursor:
                rows = await cursor.fetchall()
        embed = discord.Embed(title="💰 The Bounty Board", color=COLOR_CRIMSON)
        if not rows:
            embed.description = "The board is clear."
        for bounty_id, target_id, placed_by, amount, reason in rows:
            embed.add_field(
                name=f"#{bounty_id} {amount:,} Ovi — <@{target_id}>",
                value=f"{reason}\nposted by <@{placed_by}>",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @bounty_group.command(name="claim", description="Collect a bounty by bringing them in")
    @app_commands.describe(bounty_id="Bounty to claim")
    async def bounty_claim(self, interaction: discord.Interaction, bounty_id: int):
        claimer_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT target_id, placed_by, amount, reason FROM bounties "
                "WHERE bounty_id = ?", (bounty_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                await interaction.response.send_message(
                    f"❌ No bounty #{bounty_id} exists.", ephemeral=True)
                return
            target_id, placed_by, amount, reason = row
            if claimer_id in (target_id, placed_by):
                await interaction.response.send_message(
                    "❌ The target and the poster cannot claim a bounty.", ephemeral=True)
                return
            cursor = await db.execute(
                "UPDATE bounties SET status = 'claimed' WHERE bounty_id = ? "
                "AND status = 'active'", (bounty_id,)
            )
            changed = cursor.rowcount
            await db.commit()
        if changed != 1:
            await interaction.response.send_message(
                "❌ That bounty was just claimed or retracted.", ephemeral=True)
            return
        await self.db.add_balance(claimer_id, amount, "bounty",
                                  f"Bounty #{bounty_id} claimed")
        audit_log.info("Bounty %s claimed by %s amount=%s", bounty_id, claimer_id, amount)
        embed = discord.Embed(
            title="💰 Bounty Claimed",
            description=f"**{interaction.user.display_name}** brought in "
                        f"<@{target_id}> and collected **{amount:,} Ovi**.",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

    @bounty_group.command(name="retract", description="Withdraw your bounty and reclaim the reward")
    @app_commands.describe(bounty_id="Bounty to withdraw")
    async def bounty_retract(self, interaction: discord.Interaction, bounty_id: int):
        poster_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT placed_by, amount FROM bounties WHERE bounty_id = ?",
                (bounty_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                await interaction.response.send_message(
                    f"❌ No bounty #{bounty_id} exists.", ephemeral=True)
                return
            placed_by, amount = row
            if placed_by != poster_id:
                await interaction.response.send_message(
                    "❌ Only the poster may retract a bounty.", ephemeral=True)
                return
            cursor = await db.execute(
                "UPDATE bounties SET status = 'retracted' WHERE bounty_id = ? "
                "AND status = 'active'", (bounty_id,)
            )
            changed = cursor.rowcount
            await db.commit()
        if changed != 1:
            await interaction.response.send_message(
                "❌ That bounty is no longer active.", ephemeral=True)
            return
        await self.db.add_balance(poster_id, amount, "bounty",
                                  f"Bounty #{bounty_id} retracted")
        audit_log.info("Bounty %s retracted by %s", bounty_id, poster_id)
        embed = discord.Embed(
            title="💰 Bounty Retracted",
            description=f"#{bounty_id} is off the board — **{amount:,} Ovi** returned.",
            color=COLOR_GOLD,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Police(bot))