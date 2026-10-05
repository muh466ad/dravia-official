"""Dravia State Bot - Immigration (Border Service)

Visas live in `visas`. Citizens apply, Immigration Officers decide, and an
approved visa carries an expiry computed in SQLite so `/immigration status`
always reads fresh. Dates render through `stamp()`.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, success, warning
from utils.checks import requires_immigration_officer
from utils.validation import text

VISA_TYPES = ["Tourist", "Work", "Student", "Transit"]
DURATIONS = [30, 90, 365]

_VISA_COLS = ("visa_id", "applicant_id", "visa_type", "reason",
              "issued_at", "expires_at", "status")


class Immigration(DraviaCog):
    """Border Service commands."""

    group_name = "economy"
    immigration_group = app_commands.Group(
        name="immigration", description="Visas and border control"
    )

    # ------------------------------------------------------------ helpers
    async def _get_visa(self, visa_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM visas WHERE visa_id = ?", (visa_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_VISA_COLS, row)) if row else None

    @staticmethod
    def _visa_fields(visa) -> list[tuple[str, str]]:
        return [
            ("Applicant", f"<@{visa['applicant_id']}>" if visa["applicant_id"] else "—"),
            ("Type", visa["visa_type"] or "—"),
            ("Reason", visa["reason"] or "—"),
            ("Status", visa["status"]),
            ("Issued", stamp(visa["issued_at"]) if visa["issued_at"] else "—"),
            ("Expires", stamp(visa["expires_at"]) if visa["expires_at"] else "—"),
        ]

    # ------------------------------------------------------------ commands
    @immigration_group.command(name="apply", description="Apply for a visa")
    @app_commands.describe(visa_type="Category of visa", reason="Why you need it")
    @app_commands.choices(visa_type=[app_commands.Choice(name=v, value=v) for v in VISA_TYPES])
    @handles_validation
    async def immigration_apply(self, interaction: discord.Interaction, visa_type: str,
                                reason: str):
        reason = text(reason, field="Reason", maximum=200)
        visa_type = visa_type if visa_type in VISA_TYPES else VISA_TYPES[0]
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO visas (applicant_id, visa_type, reason, status) "
                "VALUES (?, ?, ?, 'pending')",
                (user_id, visa_type, reason),
            )
            await db.commit()
            async with db.execute("SELECT MAX(visa_id) FROM visas") as cur:
                visa_id = (await cur.fetchone())[0]
        log_action("immigration", "apply", user_id, visa=visa_id, visa_type=visa_type)
        embed = success("Application filed", f"Your **{visa_type}** visa request is queued for review.")
        embed.add_field(name="Visa ID", value=f"#{visa_id}")
        embed.add_field(name="Reason", value=reason)
        embed.set_footer(text="Track it with /immigration status")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @immigration_group.command(name="status", description="Check one visa application")
    @app_commands.describe(visa_id="Visa to read")
    async def immigration_status(self, interaction: discord.Interaction, visa_id: int):
        visa = await self._get_visa(visa_id)
        if visa is None:
            await self.fail(interaction, f"No visa #{visa_id} exists.")
            return
        embed = DraviaEmbed(title=f"🛂 Visa #{visa['visa_id']}", color=COLOR_GOLD)
        for k, v in self._visa_fields(visa):
            embed.add_field(name=k, value=v, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @immigration_group.command(name="mine", description="Your visa applications")
    async def immigration_mine(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT visa_id, visa_type, status, expires_at FROM visas "
                "WHERE applicant_id = ? ORDER BY visa_id DESC LIMIT 10",
                (str(interaction.user.id),),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🛂 Your Visas", color=COLOR_GOLD)
        if not rows:
            embed.description = "You have never applied. `/immigration apply` starts one."
        for visa_id, visa_type, status, expires_at in rows:
            expires = f" · expires {stamp(expires_at)}" if expires_at else ""
            embed.add_field(name=f"#{visa_id} {visa_type}",
                            value=f"**{status}**{expires}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @immigration_group.command(name="pending", description="Queue of undecided applications (Officer)")
    @requires_immigration_officer
    async def immigration_pending(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT visa_id, applicant_id, visa_type, reason FROM visas "
                "WHERE status = 'pending' ORDER BY visa_id LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🛂 Pending Applications", color=COLOR_GOLD)
        if not rows:
            embed.description = "The queue is clear."
        for visa_id, applicant_id, visa_type, reason in rows:
            embed.add_field(name=f"#{visa_id} {visa_type} — <@{applicant_id}>",
                            value=reason or "—")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @immigration_group.command(name="approve", description="Approve a visa (Officer)")
    @app_commands.describe(visa_id="Application to approve", duration_days="Validity in days")
    @app_commands.choices(duration_days=[app_commands.Choice(name=f"{d} days", value=d)
                                          for d in DURATIONS])
    @requires_immigration_officer
    async def immigration_approve(self, interaction: discord.Interaction, visa_id: int,
                                  duration_days: int = 90):
        visa = await self._get_visa(visa_id)
        if visa is None:
            await self.fail(interaction, f"No visa #{visa_id} exists.")
            return
        if visa["status"] != "pending":
            await self.fail(interaction, f"Visa #{visa_id} is **{visa['status']}**, not pending.")
            return
        days = duration_days if duration_days in DURATIONS else 90
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE visas SET status = 'approved', issued_at = date('now'), "
                "expires_at = date('now', ?) WHERE visa_id = ? AND status = 'pending'",
                (f"+{days} days", visa_id),
            )
            await db.commit()
        log_action("immigration", "approve", str(interaction.user.id),
                   visa=visa_id, days=days)
        embed = success("Visa approved", f"Visa #{visa_id} is valid for **{days} days**.")
        embed.add_field(name="Applicant", value=f"<@{visa['applicant_id']}>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @immigration_group.command(name="deny", description="Refuse a visa application (Officer)")
    @app_commands.describe(visa_id="Application to refuse")
    @requires_immigration_officer
    async def immigration_deny(self, interaction: discord.Interaction, visa_id: int):
        visa = await self._get_visa(visa_id)
        if visa is None:
            await self.fail(interaction, f"No visa #{visa_id} exists.")
            return
        if visa["status"] != "pending":
            await self.fail(interaction, f"Visa #{visa_id} is **{visa['status']}**, not pending.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE visas SET status = 'denied' WHERE visa_id = ?",
                             (visa_id,))
            await db.commit()
        log_action("immigration", "deny", str(interaction.user.id), visa=visa_id)
        embed = warning("Visa refused", f"Visa #{visa_id} has been denied.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @immigration_group.command(name="revoke", description="Cancel an approved visa (Officer)")
    @app_commands.describe(visa_id="Visa to cancel")
    @requires_immigration_officer
    async def immigration_revoke(self, interaction: discord.Interaction, visa_id: int):
        visa = await self._get_visa(visa_id)
        if visa is None:
            await self.fail(interaction, f"No visa #{visa_id} exists.")
            return
        if visa["status"] != "approved":
            await self.fail(interaction, f"Visa #{visa_id} is **{visa['status']}**, not approved.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE visas SET status = 'revoked' WHERE visa_id = ?",
                             (visa_id,))
            await db.commit()
        log_action("immigration", "revoke", str(interaction.user.id), visa=visa_id)
        embed = warning("Visa revoked", f"Visa #{visa_id} is no longer valid.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Immigration(bot))
