"""Dravia State Bot - Diplomacy (Foreign Office)

Embassies live in `embassies`, one per nation. Opening one costs the state a
deposit; Diplomats staff and close them. Dates render through `stamp()`.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, ovi, success, warning
from utils.checks import requires_diplomat, requires_minister
from utils.validation import text

#: Deposit paid when opening an embassy.
OPEN_COST = 2500

_EMBASSY_COLS = ("embassy_id", "nation", "ambassador_id", "opened_at", "status")


class Diplomacy(DraviaCog):
    """Foreign Office commands."""

    group_name = "economy"
    diplomacy_group = app_commands.Group(
        name="diplomacy", description="Embassies and foreign relations"
    )

    # ------------------------------------------------------------ helpers
    async def _get_embassy(self, nation: str):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM embassies WHERE nation = ? COLLATE NOCASE", (nation,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_EMBASSY_COLS, row)) if row else None

    # ------------------------------------------------------------ commands
    @diplomacy_group.command(name="open", description="Open an embassy (Diplomat, 2,500 Ovi)")
    @app_commands.describe(nation="Country to accredit")
    @handles_validation
    @requires_diplomat
    async def diplomacy_open(self, interaction: discord.Interaction, nation: str):
        nation = text(nation, field="Nation", maximum=60)
        if await self._get_embassy(nation):
            await self.fail(interaction, f"An embassy for **{nation}** already exists.")
            return
        user_id = str(interaction.user.id)
        if not await self.debit(user_id, OPEN_COST, "diplomacy", f"Embassy: {nation}"):
            await self.fail(interaction,
                            f"Opening an embassy costs {ovi(OPEN_COST)} — the mission cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO embassies (nation, ambassador_id, opened_at, status) "
                "VALUES (?, ?, date('now'), 'active')",
                (nation, user_id),
            )
            await db.commit()
        log_action("diplomacy", "open", user_id, nation=nation)
        embed = success("Embassy opened", f"Dravia now hosts a mission in **{nation}**.")
        embed.add_field(name="Deposit", value=ovi(OPEN_COST))
        embed.add_field(name="Next", value="Accredit an envoy with `/diplomacy appoint`.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @diplomacy_group.command(name="close", description="Close an embassy (Diplomat or Minister)")
    @app_commands.describe(nation="Country to cut ties with")
    @handles_validation
    async def diplomacy_close(self, interaction: discord.Interaction, nation: str):
        embassy = await self._get_embassy(nation)
        if embassy is None:
            await self.fail(interaction, f"No embassy for **{nation}** exists.")
            return
        if embassy["status"] != "active":
            await self.fail(interaction, f"The mission in **{embassy['nation']}** is already {embassy['status']}.")
            return
        if not await self._authorized(interaction):
            await self.fail(interaction, "Only a Diplomat or Minister may close a mission.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE embassies SET status = 'closed' WHERE embassy_id = ?",
                             (embassy["embassy_id"],))
            await db.commit()
        log_action("diplomacy", "close", str(interaction.user.id), nation=embassy["nation"])
        embed = warning("Relations cut", f"The embassy in **{embassy['nation']}** has been closed.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @diplomacy_group.command(name="appoint", description="Accredit an ambassador (Diplomat)")
    @app_commands.describe(nation="The mission", ambassador="Who serves there")
    @handles_validation
    @requires_diplomat
    async def diplomacy_appoint(self, interaction: discord.Interaction, nation: str,
                                ambassador: discord.Member):
        embassy = await self._get_embassy(nation)
        if embassy is None:
            await self.fail(interaction, f"No embassy for **{nation}** exists.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE embassies SET ambassador_id = ? WHERE embassy_id = ?",
                             (str(ambassador.id), embassy["embassy_id"]))
            await db.commit()
        log_action("diplomacy", "appoint", str(interaction.user.id),
                   nation=embassy["nation"], ambassador=str(ambassador.id))
        embed = success("Credentials accepted",
                        f"**{ambassador.display_name}** now serves as ambassador to **{embassy['nation']}**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @diplomacy_group.command(name="recall", description="Withdraw the ambassador (Diplomat)")
    @app_commands.describe(nation="The mission")
    @handles_validation
    @requires_diplomat
    async def diplomacy_recall(self, interaction: discord.Interaction, nation: str):
        embassy = await self._get_embassy(nation)
        if embassy is None:
            await self.fail(interaction, f"No embassy for **{nation}** exists.")
            return
        if not embassy["ambassador_id"]:
            await self.fail(interaction, f"The mission in **{embassy['nation']}** has no ambassador.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE embassies SET ambassador_id = NULL WHERE embassy_id = ?",
                             (embassy["embassy_id"],))
            await db.commit()
        log_action("diplomacy", "recall", str(interaction.user.id), nation=embassy["nation"])
        embed = warning("Ambassador recalled", f"The envoy to **{embassy['nation']}** has returned home.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @diplomacy_group.command(name="info", description="Read one embassy")
    @app_commands.describe(nation="Country to inspect")
    @handles_validation
    async def diplomacy_info(self, interaction: discord.Interaction, nation: str):
        embassy = await self._get_embassy(nation)
        if embassy is None:
            await self.fail(interaction, f"No embassy for **{nation}** exists.")
            return
        embed = DraviaEmbed(title=f"🤝 Mission to {embassy['nation']}", color=COLOR_GOLD)
        embed.add_field(name="Status", value=embassy["status"], inline=True)
        embed.add_field(
            name="Ambassador",
            value=f"<@{embassy['ambassador_id']}>" if embassy["ambassador_id"] else "Vacant",
            inline=True,
        )
        embed.add_field(name="Opened",
                        value=stamp(embassy["opened_at"]) if embassy["opened_at"] else "—",
                        inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @diplomacy_group.command(name="list", description="Every Dravian mission abroad")
    async def diplomacy_list(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT nation, status, ambassador_id, opened_at FROM embassies "
                "ORDER BY status, nation LIMIT 25"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🤝 Dravian Missions Abroad", color=COLOR_GOLD)
        if not rows:
            embed.description = "No missions yet. Diplomats open one with `/diplomacy open`."
        for nation, status, ambassador_id, opened_at in rows:
            envoy = f"<@{ambassador_id}>" if ambassador_id else "vacant"
            embed.add_field(name=nation,
                            value=f"{status} · envoy {envoy} · {stamp(opened_at)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @diplomacy_group.command(name="policy", description="Foreign Office standing (Minister)")
    @requires_minister
    async def diplomacy_policy(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT status, COUNT(*) FROM embassies GROUP BY status"
            ) as cur:
                counts = dict(await cur.fetchall())
            async with db.execute(
                "SELECT COUNT(*) FROM embassies WHERE ambassador_id IS NOT NULL "
                "AND status = 'active'"
            ) as cur:
                staffed = (await cur.fetchone())[0]
        embed = DraviaEmbed(title="🤝 Foreign Policy Standing", color=COLOR_GOLD)
        embed.add_field(name="Active missions", value=str(counts.get("active", 0)), inline=True)
        embed.add_field(name="Closed missions", value=str(counts.get("closed", 0)), inline=True)
        embed.add_field(name="Staffed (active)", value=str(staffed), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------ helpers
    async def _authorized(self, interaction) -> bool:
        """Diplomat role or Minister role (checked by name, not decorator)."""
        try:
            names = {r.name for r in interaction.user.roles}
        except Exception:
            return False
        return bool(names & {"Diplomat", "Minister", "Admin"})


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Diplomacy(bot))
