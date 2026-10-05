"""Dravia State Bot - Fire Service (Ignis Dravia)

Incidents live in `fire_incidents`. Anyone can report a fire, firefighters
attach a responding unit and resolve it, and resolving pays a severity-based
reward. All timestamps render through `stamp()` for the Dravian calendar.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, now, ovi, success, warning
from utils.checks import requires_firefighter, requires_minister
from utils.validation import text

SEVERITIES = ["Minor", "Moderate", "Severe", "Inferno"]

#: Reward paid to the firefighter who closes an incident, by severity.
RESOLVE_REWARD = {
    "Minor": 100,
    "Moderate": 200,
    "Severe": 400,
    "Inferno": 800,
}

_INCIDENT_COLS = ("incident_id", "location", "severity", "reported_at",
                  "resolved_at", "responding_unit")


class Fire(DraviaCog):
    """Fire Service commands."""

    group_name = "police"
    fire_group = app_commands.Group(name="fire", description="Fire Service commands")

    # ------------------------------------------------------------ helpers
    async def _get_incident(self, incident_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM fire_incidents WHERE incident_id = ?", (incident_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_INCIDENT_COLS, row)) if row else None

    def _incident_fields(self, inc) -> list[tuple[str, str]]:
        return [
            ("Location", inc["location"] or "—"),
            ("Severity", inc["severity"] or "—"),
            ("Reported", stamp(inc["reported_at"]) if inc["reported_at"] else "—"),
            ("Responding unit", inc["responding_unit"] or "Unassigned"),
            ("Resolved", stamp(inc["resolved_at"]) if inc["resolved_at"] else "Still burning"),
        ]

    # ------------------------------------------------------------ commands
    @fire_group.command(name="report", description="Report a fire")
    @app_commands.describe(location="Where it is burning", severity="How bad it is")
    @app_commands.choices(severity=[app_commands.Choice(name=s, value=s) for s in SEVERITIES])
    @handles_validation
    async def fire_report(self, interaction: discord.Interaction, location: str,
                          severity: str = "Moderate"):
        location = text(location, field="Location", maximum=80)
        severity = severity if severity in SEVERITIES else "Moderate"
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO fire_incidents (location, severity, reported_at) VALUES (?, ?, ?)",
                (location, severity, now()),
            )
            await db.commit()
            async with db.execute("SELECT MAX(incident_id) FROM fire_incidents") as cur:
                incident_id = (await cur.fetchone())[0]
        log_action("fire", "report", str(interaction.user.id), incident=incident_id,
                   severity=severity, location=location)
        embed = warning("Fire reported", f"**{severity}** fire at **{location}**.")
        embed.add_field(name="Incident ID", value=f"#{incident_id}")
        embed.add_field(name="Next", value="Firefighters dispatch with `/fire dispatch`.")
        await interaction.response.send_message(embed=embed)

    @fire_group.command(name="dispatch", description="Assign your unit to an incident (Firefighter)")
    @app_commands.describe(incident_id="Incident to attend", unit="Your responding unit")
    @handles_validation
    @requires_firefighter
    async def fire_dispatch(self, interaction: discord.Interaction, incident_id: int, unit: str):
        incident = await self._get_incident(incident_id)
        if incident is None:
            await self.fail(interaction, f"No incident #{incident_id} exists.")
            return
        if incident["resolved_at"]:
            await self.fail(interaction, f"Incident #{incident_id} is already resolved.")
            return
        unit = text(unit, field="Unit", maximum=40)
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE fire_incidents SET responding_unit = ? WHERE incident_id = ?",
                (unit, incident_id),
            )
            await db.commit()
        log_action("fire", "dispatch", str(interaction.user.id), incident=incident_id, unit=unit)
        embed = success("Unit dispatched", f"**{unit}** is en route to incident #{incident_id}.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fire_group.command(name="resolve", description="Close an incident (Firefighter, pays a reward)")
    @app_commands.describe(incident_id="Incident to put out")
    @requires_firefighter
    async def fire_resolve(self, interaction: discord.Interaction, incident_id: int):
        incident = await self._get_incident(incident_id)
        if incident is None:
            await self.fail(interaction, f"No incident #{incident_id} exists.")
            return
        if incident["resolved_at"]:
            await self.fail(interaction, f"Incident #{incident_id} is already resolved.")
            return
        async with await self.db.get_connection() as db:
            # Guard in the statement so a double-submit cannot pay twice.
            cur = await db.execute(
                "UPDATE fire_incidents SET resolved_at = ? WHERE incident_id = ? "
                "AND resolved_at IS NULL",
                (now(), incident_id),
            )
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"Incident #{incident_id} was just resolved by someone else.")
            return
        reward = RESOLVE_REWARD.get(incident["severity"], 100)
        await self.credit(str(interaction.user.id), reward, "fire",
                          f"Incident #{incident_id} resolved")
        log_action("fire", "resolve", str(interaction.user.id), incident=incident_id)
        embed = success("Fire out", f"Incident #{incident_id} at **{incident['location']}** is under control.")
        embed.add_field(name="Reward", value=ovi(reward))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fire_group.command(name="status", description="Read one incident")
    @app_commands.describe(incident_id="Incident to inspect")
    async def fire_status(self, interaction: discord.Interaction, incident_id: int):
        incident = await self._get_incident(incident_id)
        if incident is None:
            await self.fail(interaction, f"No incident #{incident_id} exists.")
            return
        embed = DraviaEmbed(title=f"🔥 Incident #{incident['incident_id']}", color=COLOR_GOLD)
        for k, v in self._incident_fields(incident):
            embed.add_field(name=k, value=v, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fire_group.command(name="log", description="Open incidents awaiting a crew")
    async def fire_log(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT incident_id, location, severity, responding_unit "
                "FROM fire_incidents WHERE resolved_at IS NULL "
                "ORDER BY incident_id DESC LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🔥 Open Incident Log", color=COLOR_GOLD)
        if not rows:
            embed.description = "No open incidents. The Republic is safe — for now."
        for incident_id, location, severity, unit in rows:
            embed.add_field(
                name=f"#{incident_id} {severity} — {location}",
                value=f"Crew: {unit or 'unassigned'}",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fire_group.command(name="history", description="Recently resolved incidents")
    async def fire_history(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT incident_id, location, severity, responding_unit, resolved_at "
                "FROM fire_incidents WHERE resolved_at IS NOT NULL "
                "ORDER BY incident_id DESC LIMIT 10"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🔥 Recent Calls", color=COLOR_GOLD)
        if not rows:
            embed.description = "No incidents have been resolved yet."
        for incident_id, location, severity, unit, resolved_at in rows:
            embed.add_field(
                name=f"#{incident_id} {severity} — {location}",
                value=f"{unit or 'unassigned'} · {stamp(resolved_at)}",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fire_group.command(name="stations", description="Fire Service order of battle (Minister)")
    @requires_minister
    async def fire_stations(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT severity, COUNT(*) FROM fire_incidents GROUP BY severity"
            ) as cur:
                by_severity = dict(await cur.fetchall())
            async with db.execute(
                "SELECT COUNT(*) FROM fire_incidents WHERE resolved_at IS NULL"
            ) as cur:
                open_count = (await cur.fetchone())[0]
        embed = DraviaEmbed(title="🔥 Fire Service Overview", color=COLOR_GOLD)
        for severity in SEVERITIES:
            embed.add_field(name=severity, value=f"{by_severity.get(severity, 0)} call(s)", inline=True)
        embed.add_field(name="Open incidents", value=str(open_count), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Fire(bot))
