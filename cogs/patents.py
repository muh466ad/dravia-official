"""Dravia State Bot - Patents (Office of Industrial Property)

Records live in `patents`. Citizens file inventions for a fee, the Patent
Officer grants or refuses them, and a granted patent runs a five-year term.
Dates render through `stamp()`.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, ovi, success, warning
from utils.checks import requires_patent_officer
from utils.validation import text

FILING_FEE = 750
RENEWAL_FEE = 500
#: SQLite interval applied on grant.
TERM = "+5 years"

_PATENT_COLS = ("patent_id", "holder_id", "invention", "description",
                "filed_at", "granted_at", "expires_at", "status")


class Patents(DraviaCog):
    """Office of Industrial Property commands."""

    group_name = "economy"
    patent_group = app_commands.Group(name="patent", description="Patents and inventions")

    # ------------------------------------------------------------ helpers
    async def _get_patent(self, patent_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM patents WHERE patent_id = ?", (patent_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_PATENT_COLS, row)) if row else None

    @staticmethod
    def _fields(patent) -> list[tuple[str, str]]:
        return [
            ("Holder", f"<@{patent['holder_id']}>" if patent["holder_id"] else "—"),
            ("Status", patent["status"]),
            ("Filed", stamp(patent["filed_at"]) if patent["filed_at"] else "—"),
            ("Granted", stamp(patent["granted_at"]) if patent["granted_at"] else "—"),
            ("Term expires", stamp(patent["expires_at"]) if patent["expires_at"] else "—"),
        ]

    # ------------------------------------------------------------ commands
    @patent_group.command(name="file", description="File an invention (750 Ovi)")
    @app_commands.describe(invention="Short title of the invention",
                           details="What it does")
    @handles_validation
    async def patent_file(self, interaction: discord.Interaction, invention: str,
                          details: str):
        invention = text(invention, field="Invention", maximum=80)
        details = text(details, field="Details", maximum=400)
        user_id = str(interaction.user.id)
        if not await self.debit(user_id, FILING_FEE, "patent", f"Filed: {invention}"):
            await self.fail(interaction,
                            f"Filing costs {ovi(FILING_FEE)} — you cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO patents (holder_id, invention, description, filed_at, status) "
                "VALUES (?, ?, ?, date('now'), 'pending')",
                (user_id, invention, details),
            )
            await db.commit()
            async with db.execute("SELECT MAX(patent_id) FROM patents") as cur:
                patent_id = (await cur.fetchone())[0]
        log_action("patent", "file", user_id, patent=patent_id, invention=invention)
        embed = success("Application filed", f"**{invention}** awaits examination.")
        embed.add_field(name="Patent ID", value=f"#{patent_id}")
        embed.add_field(name="Fee", value=ovi(FILING_FEE))
        embed.add_field(name="Next", value="The Patent Officer rules with `/patent grant`.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @patent_group.command(name="info", description="Read one patent")
    @app_commands.describe(patent_id="Patent to inspect")
    async def patent_info(self, interaction: discord.Interaction, patent_id: int):
        patent = await self._get_patent(patent_id)
        if patent is None:
            await self.fail(interaction, f"No patent #{patent_id} exists.")
            return
        embed = DraviaEmbed(title=f"📜 {patent['invention']}", color=COLOR_GOLD)
        embed.description = (patent["description"] or "—")[:400]
        for k, v in self._fields(patent):
            embed.add_field(name=k, value=v, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @patent_group.command(name="mine", description="Your patent portfolio")
    async def patent_mine(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT patent_id, invention, status, expires_at FROM patents "
                "WHERE holder_id = ? ORDER BY patent_id DESC LIMIT 12",
                (str(interaction.user.id),),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="📜 Your Patents", color=COLOR_GOLD)
        if not rows:
            embed.description = "You have filed nothing. `/patent file` starts one."
        for patent_id, invention, status, expires_at in rows:
            extra = f" · term {stamp(expires_at)}" if expires_at else ""
            embed.add_field(name=f"#{patent_id} {invention}", value=f"**{status}**{extra}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @patent_group.command(name="pending", description="Awaiting examination (Patent Officer)")
    @requires_patent_officer
    async def patent_pending(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT patent_id, holder_id, invention, filed_at FROM patents "
                "WHERE status = 'pending' ORDER BY patent_id LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="📜 Examination Queue", color=COLOR_GOLD)
        if not rows:
            embed.description = "Nothing to examine."
        for patent_id, holder_id, invention, filed_at in rows:
            embed.add_field(name=f"#{patent_id} {invention}",
                            value=f"<@{holder_id}> · filed {stamp(filed_at) if filed_at else '—'}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @patent_group.command(name="grant", description="Grant a patent (Patent Officer)")
    @app_commands.describe(patent_id="Application to grant")
    @requires_patent_officer
    async def patent_grant(self, interaction: discord.Interaction, patent_id: int):
        patent = await self._get_patent(patent_id)
        if patent is None:
            await self.fail(interaction, f"No patent #{patent_id} exists.")
            return
        if patent["status"] != "pending":
            await self.fail(interaction, f"Patent #{patent_id} is **{patent['status']}**.")
            return
        async with await self.db.get_connection() as db:
            cur = await db.execute(
                "UPDATE patents SET status = 'granted', granted_at = date('now'), "
                "expires_at = date('now', ?) WHERE patent_id = ? AND status = 'pending'",
                (TERM, patent_id),
            )
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"Patent #{patent_id} was just examined by someone else.")
            return
        log_action("patent", "grant", str(interaction.user.id), patent=patent_id)
        embed = success("Patent granted",
                        f"**{patent['invention']}** holds a five-year exclusive term.")
        embed.add_field(name="Holder", value=f"<@{patent['holder_id']}>")
        embed.set_footer(text="Renew before expiry with /patent renew")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @patent_group.command(name="reject", description="Refuse an application (Patent Officer)")
    @app_commands.describe(patent_id="Application to refuse")
    @requires_patent_officer
    async def patent_reject(self, interaction: discord.Interaction, patent_id: int):
        patent = await self._get_patent(patent_id)
        if patent is None:
            await self.fail(interaction, f"No patent #{patent_id} exists.")
            return
        if patent["status"] != "pending":
            await self.fail(interaction, f"Patent #{patent_id} is **{patent['status']}**.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE patents SET status = 'rejected' WHERE patent_id = ?",
                             (patent_id,))
            await db.commit()
        log_action("patent", "reject", str(interaction.user.id), patent=patent_id)
        embed = warning("Application refused", f"Patent #{patent_id} has been rejected.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @patent_group.command(name="renew", description="Extend a granted term by five years (500 Ovi)")
    @app_commands.describe(patent_id="Patent to renew")
    async def patent_renew(self, interaction: discord.Interaction, patent_id: int):
        patent = await self._get_patent(patent_id)
        if patent is None:
            await self.fail(interaction, f"No patent #{patent_id} exists.")
            return
        if patent["status"] != "granted":
            await self.fail(interaction, f"Only granted patents can renew (#{patent_id} is {patent['status']}).")
            return
        if patent["holder_id"] != str(interaction.user.id):
            await self.fail(interaction, "Only the patent holder may renew it.")
            return
        if not await self.debit(str(interaction.user.id), RENEWAL_FEE, "patent",
                                f"Renewed #{patent_id}"):
            await self.fail(interaction, f"Renewal costs {ovi(RENEWAL_FEE)} — you cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE patents SET expires_at = date(expires_at, ?) WHERE patent_id = ?",
                (TERM, patent_id),
            )
            await db.commit()
            async with db.execute("SELECT expires_at FROM patents WHERE patent_id = ?",
                                  (patent_id,)) as cur:
                expires = (await cur.fetchone())[0]
        log_action("patent", "renew", str(interaction.user.id), patent=patent_id)
        embed = success("Term extended", f"**{patent['invention']}** now runs to {stamp(expires)}.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @patent_group.command(name="search", description="Search the public register")
    @app_commands.describe(term="Invention title fragment")
    @handles_validation
    async def patent_search(self, interaction: discord.Interaction, term: str):
        term = text(term, field="Search", maximum=40)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT patent_id, invention, status FROM patents "
                "WHERE invention LIKE ? ORDER BY patent_id DESC LIMIT 10",
                (f"%{term}%",),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title=f"📜 Register search: {term}", color=COLOR_GOLD)
        if not rows:
            embed.description = "Nothing matched."
        for patent_id, invention, status in rows:
            embed.add_field(name=f"#{patent_id} {invention}", value=f"**{status}**")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Patents(bot))
