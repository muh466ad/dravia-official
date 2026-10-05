"""Dravia State Bot - Military (Defence Forces of Dravia)

Units are the state of the table `military_units`: citizens fund and enlist in
them, commanders move them around, and the Minister can review or disband any
of them. Strength models personnel — it moves with enlistments and drills.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, ovi, success, warning
from utils.checks import requires_soldier
from utils.validation import text

BRANCHES = ["Army", "Navy", "Air Force"]

#: Ovi cost to raise a new unit / to run a drill that adds strength.
RECRUIT_COST = 1000
DRILL_COST = 500
DRILL_STRENGTH = 2


class Military(DraviaCog):
    """Defence Forces commands."""

    group_name = "police"
    military_group = app_commands.Group(
        name="military", description="Defence Forces of Dravia unit commands"
    )

    # ------------------------------------------------------------ helpers
    async def _get_unit(self, unit_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM military_units WHERE unit_id = ?", (unit_id,)
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        cols = ["unit_id", "name", "branch", "commander_id", "location",
                "strength", "status"]
        return dict(zip(cols, row))

    def _may_command(self, interaction, unit) -> bool:
        """The unit's commander, or a Minister."""
        if str(interaction.user.id) == str(unit["commander_id"]):
            return True
        try:
            return interaction.user.guild_permissions.administrator
        except Exception:
            return False

    @staticmethod
    def _unit_fields(unit) -> list[tuple[str, str]]:
        return [
            ("Branch", unit["branch"]),
            ("Commander", f"<@{unit['commander_id']}>" if unit["commander_id"] else "—"),
            ("Location", unit["location"] or "—"),
            ("Strength", f"{unit['strength']:,} troops"),
            ("Status", unit["status"]),
        ]

    # ------------------------------------------------------------ commands
    @military_group.command(name="recruit", description="Raise a new military unit (costs 1,000 Ovi)")
    @app_commands.describe(name="Unit name", branch="Service branch")
    @app_commands.choices(branch=[app_commands.Choice(name=b, value=b) for b in BRANCHES])
    @handles_validation
    @requires_soldier
    async def military_recruit(self, interaction: discord.Interaction, name: str, branch: str):
        name = text(name, field="Unit name", maximum=60)
        branch = branch if branch in BRANCHES else BRANCHES[0]
        user_id = str(interaction.user.id)
        if not await self.debit(user_id, RECRUIT_COST, "military", f"Raised unit {name}"):
            await self.fail(interaction, f"Raising a unit costs {ovi(RECRUIT_COST)} — you cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO military_units (name, branch, commander_id, location, strength, status) "
                "VALUES (?, ?, ?, ?, 10, 'active')",
                (name, branch, user_id, "Capital Barracks"),
            )
            await db.commit()
            async with db.execute("SELECT MAX(unit_id) FROM military_units") as cur:
                unit_id = (await cur.fetchone())[0]
        log_action("military", "recruit", user_id, unit=unit_id, name=name, branch=branch)
        embed = success("Unit raised", f"**{name}** ({branch}) stands at **Capital Barracks** with 10 troops.")
        embed.add_field(name="Cost", value=ovi(RECRUIT_COST))
        embed.add_field(name="Unit ID", value=f"#{unit_id}")
        embed.add_field(name="Next", value="Citizens join with `/military enlist`, commanders drill with `/military drill`.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @military_group.command(name="enlist", description="Enlist in the smallest active unit (+1 strength)")
    @app_commands.describe(unit_id="Unit to join (defaults to the smallest)")
    async def military_enlist(self, interaction: discord.Interaction, unit_id: int = 0):
        if unit_id:
            unit = await self._get_unit(unit_id)
        else:
            async with await self.db.get_connection() as db:
                async with db.execute(
                    "SELECT unit_id, name, branch, commander_id, location, strength, status "
                    "FROM military_units WHERE status = 'active' ORDER BY strength ASC LIMIT 1"
                ) as cur:
                    row = await cur.fetchone()
            unit = dict(zip(
                ["unit_id", "name", "branch", "commander_id", "location", "strength", "status"],
                row)) if row else None
        if unit is None:
            await self.fail(interaction, "No active unit to enlist in. Raise one with `/military recruit`.")
            return
        if unit["status"] != "active":
            await self.fail(interaction, f"**{unit['name']}** is {unit['status']} and not accepting recruits.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE military_units SET strength = strength + 1 WHERE unit_id = ?",
                (unit["unit_id"],),
            )
            await db.commit()
        log_action("military", "enlist", str(interaction.user.id), unit=unit["unit_id"])
        embed = success("Enlisted", f"You joined **{unit['name']}** ({unit['branch']}).")
        embed.add_field(name="Strength", value=f"{unit['strength'] + 1:,} troops")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @military_group.command(name="roster", description="List every military unit")
    async def military_roster(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT unit_id, name, branch, location, strength, status "
                "FROM military_units ORDER BY strength DESC"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🎖️ Order of Battle", color=COLOR_GOLD)
        if not rows:
            embed.description = "No units exist yet. Raise the first with `/military recruit`."
        for unit_id, name, branch, location, strength, status in rows[:25]:
            embed.add_field(
                name=f"#{unit_id} {name}",
                value=f"{branch} · {strength:,} troops · {status}\n{location or '—'}",
            )
        embed.set_footer(text=f"{len(rows)} unit(s) | Republic of Dravia")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @military_group.command(name="status", description="Full report on one unit")
    @app_commands.describe(unit_id="The unit to inspect")
    async def military_status(self, interaction: discord.Interaction, unit_id: int):
        unit = await self._get_unit(unit_id)
        if unit is None:
            await self.fail(interaction, f"No unit #{unit_id} exists.")
            return
        embed = DraviaEmbed(title=f"🎖️ {unit['name']}", color=COLOR_GOLD)
        for k, v in self._unit_fields(unit):
            embed.add_field(name=k, value=v, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @military_group.command(name="deploy", description="Move a unit to a new location (commander only)")
    @app_commands.describe(unit_id="Unit to move", location="New posting")
    @handles_validation
    async def military_deploy(self, interaction: discord.Interaction, unit_id: int, location: str):
        unit = await self._get_unit(unit_id)
        if unit is None:
            await self.fail(interaction, f"No unit #{unit_id} exists.")
            return
        if not self._may_command(interaction, unit):
            await self.fail(interaction, "Only the unit's commander may move it.")
            return
        location = text(location, field="Location", maximum=60)
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE military_units SET location = ? WHERE unit_id = ?",
                             (location, unit_id))
            await db.commit()
        log_action("military", "deploy", str(interaction.user.id), unit=unit_id, location=location)
        embed = success("Orders issued", f"**{unit['name']}** redeployed to **{location}**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @military_group.command(name="drill", description="Run a drill: +2 strength for 500 Ovi")
    @app_commands.describe(unit_id="Unit to train")
    async def military_drill(self, interaction: discord.Interaction, unit_id: int):
        unit = await self._get_unit(unit_id)
        if unit is None:
            await self.fail(interaction, f"No unit #{unit_id} exists.")
            return
        if unit["status"] != "active":
            await self.fail(interaction, f"**{unit['name']}** is {unit['status']} and cannot drill.")
            return
        if not self._may_command(interaction, unit):
            await self.fail(interaction, "Only the unit's commander may order a drill.")
            return
        if not await self.debit(str(interaction.user.id), DRILL_COST, "military", f"Drill: {unit['name']}"):
            await self.fail(interaction, f"A drill costs {ovi(DRILL_COST)} — you cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE military_units SET strength = strength + ? WHERE unit_id = ?",
                             (DRILL_STRENGTH, unit_id))
            await db.commit()
        log_action("military", "drill", str(interaction.user.id), unit=unit_id)
        embed = success("Drill complete", f"**{unit['name']}** gained {DRILL_STRENGTH} strength.")
        embed.add_field(name="Strength", value=f"{unit['strength'] + DRILL_STRENGTH:,} troops")
        embed.add_field(name="Cost", value=ovi(DRILL_COST))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @military_group.command(name="disband", description="Disband a unit permanently (commander or Minister)")
    @app_commands.describe(unit_id="Unit to disband")
    async def military_disband(self, interaction: discord.Interaction, unit_id: int):
        unit = await self._get_unit(unit_id)
        if unit is None:
            await self.fail(interaction, f"No unit #{unit_id} exists.")
            return
        if not (self._may_command(interaction, unit) or await self._is_minister(interaction)):
            await self.fail(interaction, "Only the unit's commander or a Minister may disband it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE military_units SET status = 'disbanded' WHERE unit_id = ?",
                             (unit_id,))
            await db.commit()
        log_action("military", "disband", str(interaction.user.id), unit=unit_id)
        embed = warning("Unit disbanded", f"**{unit['name']}** has been struck from the Order of Battle.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _is_minister(self, interaction) -> bool:
        try:
            return any(r.name == "Minister" for r in interaction.user.roles)
        except Exception:
            return False


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Military(bot))
