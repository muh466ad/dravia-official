"""Dravia State Bot - Intelligence (State Security Service)

Missions live in `intel_missions`. Agents open and close them, the Minister
declassifies, and completing a mission pays a small intelligence stipend.
Every date shown to players goes through `stamp()` so the Dravian calendar
stays consistent with the rest of the Republic.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, ovi, success, warning
from utils.checks import requires_agent, requires_minister
from utils.validation import text

AGENCIES = ["State Security Service", "Foreign Intelligence Service", "Military Intelligence"]
CLASSIFICATIONS = ["Public", "Secret", "Top Secret"]

#: Stipend paid to the agent who completes a mission.
COMPLETION_PAYOUT = 250

_MISSION_COLS = ("mission_id", "agency", "target", "objective", "status",
                 "classification", "authorized_by", "started_at", "completed_at")


class Intelligence(DraviaCog):
    """State Security Service commands."""

    group_name = "police"
    intel_group = app_commands.Group(
        name="intel", description="Intelligence mission commands"
    )

    # ------------------------------------------------------------ helpers
    async def _get_mission(self, mission_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM intel_missions WHERE mission_id = ?", (mission_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_MISSION_COLS, row)) if row else None

    def _mission_fields(self, mission) -> list[tuple[str, str]]:
        return [
            ("Agency", mission["agency"]),
            ("Target", mission["target"] or "—"),
            ("Objective", mission["objective"] or "—"),
            ("Classification", mission["classification"] or "—"),
            ("Status", mission["status"]),
            ("Opened", stamp(mission["started_at"]) if mission["started_at"] else "—"),
            ("Closed", stamp(mission["completed_at"]) if mission["completed_at"] else "—"),
        ]

    # ------------------------------------------------------------ commands
    @intel_group.command(name="brief", description="Open a new mission (Agent only)")
    @app_commands.describe(agency="Running agency", target="Who or what we watch",
                           objective="The mission goal", classification="Handling level")
    @app_commands.choices(
        agency=[app_commands.Choice(name=a, value=a) for a in AGENCIES],
        classification=[app_commands.Choice(name=c, value=c) for c in CLASSIFICATIONS],
    )
    @handles_validation
    @requires_agent
    async def intel_brief(self, interaction: discord.Interaction, agency: str,
                          target: str, objective: str, classification: str = "Secret"):
        target = text(target, field="Target", maximum=80)
        objective = text(objective, field="Objective", maximum=200)
        agency = agency if agency in AGENCIES else AGENCIES[0]
        classification = classification if classification in CLASSIFICATIONS else "Secret"
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO intel_missions (agency, target, objective, status, classification, "
                "authorized_by, started_at) VALUES (?, ?, ?, 'active', ?, ?, date('now'))",
                (agency, target, objective, classification, user_id),
            )
            await db.commit()
            async with db.execute("SELECT MAX(mission_id) FROM intel_missions") as cur:
                mission_id = (await cur.fetchone())[0]
        log_action("intel", "brief", user_id, mission=mission_id, agency=agency,
                   classification=classification)
        embed = success("Mission opened", f"**{objective}**")
        embed.add_field(name="Mission ID", value=f"#{mission_id}")
        embed.add_field(name="Agency", value=agency)
        embed.add_field(name="Classification", value=classification)
        embed.add_field(name="Target", value=target)
        embed.set_footer(text="Close it with /intel complete or /intel compromise")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @intel_group.command(name="list", description="List missions by status")
    @app_commands.describe(status="Filter (defaults to active)")
    @app_commands.choices(status=[
        app_commands.Choice(name="Active", value="active"),
        app_commands.Choice(name="Completed", value="completed"),
        app_commands.Choice(name="Compromised", value="compromised"),
        app_commands.Choice(name="All", value="all"),
    ])
    async def intel_list(self, interaction: discord.Interaction, status: str = "active"):
        query = ("SELECT mission_id, agency, target, classification, status "
                 "FROM intel_missions")
        params: tuple = ()
        if status != "all":
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY mission_id DESC LIMIT 15"
        async with await self.db.get_connection() as db:
            async with db.execute(query, params) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title=f"🕵️ Missions ({status})", color=COLOR_GOLD)
        if not rows:
            embed.description = "Nothing on file. Agents open one with `/intel brief`."
        for mission_id, agency, target, classification, st in rows:
            embed.add_field(
                name=f"#{mission_id} {target or 'unnamed target'}",
                value=f"{agency} · {classification} · **{st}**",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @intel_group.command(name="status", description="Full dossier on one mission")
    @app_commands.describe(mission_id="Mission to read")
    async def intel_status(self, interaction: discord.Interaction, mission_id: int):
        mission = await self._get_mission(mission_id)
        if mission is None:
            await self.fail(interaction, f"No mission #{mission_id} exists.")
            return
        embed = DraviaEmbed(title=f"🕵️ Mission #{mission['mission_id']}", color=COLOR_GOLD)
        for k, v in self._mission_fields(mission):
            embed.add_field(name=k, value=v, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @intel_group.command(name="complete", description="Close a mission as a success (Agent only)")
    @app_commands.describe(mission_id="Mission to close")
    @requires_agent
    async def intel_complete(self, interaction: discord.Interaction, mission_id: int):
        mission = await self._get_mission(mission_id)
        if mission is None:
            await self.fail(interaction, f"No mission #{mission_id} exists.")
            return
        if mission["status"] != "active":
            await self.fail(interaction, f"Mission #{mission_id} is already **{mission['status']}**.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE intel_missions SET status = 'completed', completed_at = date('now') "
                "WHERE mission_id = ? AND status = 'active'",
                (mission_id,),
            )
            await db.commit()
        await self.credit(str(interaction.user.id), COMPLETION_PAYOUT, "intel",
                          f"Mission #{mission_id} completed")
        log_action("intel", "complete", str(interaction.user.id), mission=mission_id)
        embed = success("Mission accomplished", f"**{mission['objective'] or f'Mission #{mission_id}'}** is closed.")
        embed.add_field(name="Stipend", value=ovi(COMPLETION_PAYOUT))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @intel_group.command(name="compromise", description="Mark a mission blown (Agent only)")
    @app_commands.describe(mission_id="Mission to burn")
    @requires_agent
    async def intel_compromise(self, interaction: discord.Interaction, mission_id: int):
        mission = await self._get_mission(mission_id)
        if mission is None:
            await self.fail(interaction, f"No mission #{mission_id} exists.")
            return
        if mission["status"] != "active":
            await self.fail(interaction, f"Mission #{mission_id} is already **{mission['status']}**.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE intel_missions SET status = 'compromised', completed_at = date('now') "
                "WHERE mission_id = ? AND status = 'active'",
                (mission_id,),
            )
            await db.commit()
        log_action("intel", "compromise", str(interaction.user.id), mission=mission_id)
        embed = warning("Cover blown", f"Mission #{mission_id} has been **compromised**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @intel_group.command(name="declassify", description="Lower a mission's classification (Minister only)")
    @app_commands.describe(mission_id="Mission to declassify")
    @requires_minister
    async def intel_declassify(self, interaction: discord.Interaction, mission_id: int):
        mission = await self._get_mission(mission_id)
        if mission is None:
            await self.fail(interaction, f"No mission #{mission_id} exists.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE intel_missions SET classification = 'Public' WHERE mission_id = ?",
                (mission_id,),
            )
            await db.commit()
        log_action("intel", "declassify", str(interaction.user.id), mission=mission_id)
        embed = success("Declassified", f"Mission #{mission_id} is now **Public**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Intelligence(bot))
