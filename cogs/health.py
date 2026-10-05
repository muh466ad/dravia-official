"""Dravia State Bot - Health (Ministry of Health)

Records live in `health_records`. Citizens pay for check-ups, Doctors treat
patients for a stipend, and every encounter lands in the patient's history.
Dates render through `stamp()`.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, ovi, success, warning
from utils.checks import requires_doctor
from utils.validation import text

#: Fees paid by the patient.
CHECKUP_FEE = 150

#: Stipend paid to the Doctor for a treatment.
TREATMENT_STIPEND = 120

CLINIC = "People's Polyclinic"

_RECORD_COLS = ("record_id", "user_id", "condition", "treatment",
                "facility", "date", "doctor_id")


class Health(DraviaCog):
    """Ministry of Health commands."""

    group_name = "economy"
    health_group = app_commands.Group(name="health", description="Health records and care")

    # ------------------------------------------------------------ helpers
    async def _record_fields(self, row) -> list[tuple[str, str]]:
        record_id, user_id, condition, treatment, facility, rec_date, doctor_id = row
        return [
            ("Patient", f"<@{user_id}>" if user_id else "—"),
            ("Condition", condition or "—"),
            ("Treatment", treatment or "—"),
            ("Facility", facility or "—"),
            ("Attending", f"<@{doctor_id}>" if doctor_id else "—"),
            ("Date", stamp(rec_date) if rec_date else "—"),
        ]

    # ------------------------------------------------------------ commands
    @health_group.command(name="checkup", description="Routine check-up at the state clinic (150 Ovi)")
    async def health_checkup(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        if not await self.debit(user_id, CHECKUP_FEE, "health", "Routine check-up"):
            await self.fail(interaction,
                            f"A check-up costs {ovi(CHECKUP_FEE)} — you cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO health_records (user_id, condition, treatment, facility, date) "
                "VALUES (?, 'Routine check-up', 'Declared fit for service', ?, date('now'))",
                (user_id, CLINIC),
            )
            await db.commit()
        log_action("health", "checkup", user_id)
        embed = success("Fit for duty", "The clinic has filed your record — no complaints found.")
        embed.add_field(name="Fee", value=ovi(CHECKUP_FEE))
        embed.add_field(name="Facility", value=CLINIC)
        embed.add_field(name="History", value="Review it with `/health history`.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @health_group.command(name="treat", description="Treat a patient (Doctor, pays a stipend)")
    @app_commands.describe(patient="Who you are treating", condition="What ails them",
                           treatment="What you did about it")
    @handles_validation
    @requires_doctor
    async def health_treat(self, interaction: discord.Interaction, patient: discord.Member,
                           condition: str, treatment: str):
        condition = text(condition, field="Condition", maximum=120)
        treatment = text(treatment, field="Treatment", maximum=120)
        doctor_id = str(interaction.user.id)
        patient_id = str(patient.id)
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO health_records (user_id, condition, treatment, facility, date, doctor_id) "
                "VALUES (?, ?, ?, ?, date('now'), ?)",
                (patient_id, condition, treatment, CLINIC, doctor_id),
            )
            await db.commit()
        await self.credit(doctor_id, TREATMENT_STIPEND, "health",
                          f"Treated {patient.display_name}")
        log_action("health", "treat", doctor_id, patient=patient_id, condition=condition)
        embed = success("Patient treated", f"**{patient.display_name}** — {condition}")
        embed.add_field(name="Treatment", value=treatment)
        embed.add_field(name="Stipend", value=ovi(TREATMENT_STIPEND))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @health_group.command(name="history", description="A citizen's health history")
    @app_commands.describe(user="Whose records (defaults to you)")
    async def health_history(self, interaction: discord.Interaction,
                             user: discord.Member = None):
        target = user or interaction.user
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT record_id, user_id, condition, treatment, facility, date, doctor_id "
                "FROM health_records WHERE user_id = ? ORDER BY record_id DESC LIMIT 10",
                (str(target.id),),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title=f"🏥 Health History — {target.display_name}", color=COLOR_GOLD)
        if not rows:
            embed.description = "No records on file. `/health checkup` opens one."
        for row in rows:
            rec_date = row[5]
            embed.add_field(name=f"#{row[0]} {row[2] or '—'}",
                            value=f"{row[3] or '—'} · {row[4] or '—'} · {stamp(rec_date) if rec_date else '—'}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @health_group.command(name="records", description="Latest records across all patients (Doctor)")
    @requires_doctor
    async def health_records(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT record_id, user_id, condition, date FROM health_records "
                "ORDER BY record_id DESC LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🏥 Ward Round", color=COLOR_GOLD)
        if not rows:
            embed.description = "No records yet."
        for record_id, user_id, condition, rec_date in rows:
            embed.add_field(name=f"#{record_id} {condition or '—'}",
                            value=f"<@{user_id}> · {stamp(rec_date) if rec_date else '—'}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @health_group.command(name="vitals", description="Your care summary at a glance")
    async def health_vitals(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COUNT(*), MAX(date) FROM health_records WHERE user_id = ?",
                (user_id,),
            ) as cur:
                count, last_date = await cur.fetchone()
            async with db.execute(
                "SELECT COUNT(DISTINCT doctor_id) FROM health_records "
                "WHERE doctor_id IS NOT NULL"
            ) as cur:
                doctors = (await cur.fetchone())[0]
        embed = DraviaEmbed(title=f"🏥 Vitals — {interaction.user.display_name}", color=COLOR_GOLD)
        embed.add_field(name="Records on file", value=str(count), inline=True)
        embed.add_field(name="Last visit",
                        value=stamp(last_date) if last_date else "Never", inline=True)
        embed.add_field(name="Practising Doctors", value=str(doctors), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @health_group.command(name="clinic", description="State clinic fees and standing")
    async def health_clinic(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT COUNT(*) FROM health_records") as cur:
                total = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(DISTINCT doctor_id) FROM health_records "
                "WHERE doctor_id IS NOT NULL"
            ) as cur:
                doctors = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM health_records WHERE date = date('now')"
            ) as cur:
                today = (await cur.fetchone())[0]
        embed = DraviaEmbed(title=f"🏥 {CLINIC}", color=COLOR_GOLD)
        embed.add_field(name="Check-up fee", value=ovi(CHECKUP_FEE), inline=True)
        embed.add_field(name="Treatment stipend", value=ovi(TREATMENT_STIPEND), inline=True)
        embed.add_field(name="Doctors on staff", value=str(doctors), inline=True)
        embed.add_field(name="Records filed", value=str(total), inline=True)
        embed.add_field(name="Seen today", value=str(today), inline=True)
        embed.add_field(name="Commands", value="`/health checkup` · `/health treat` · `/health history`")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Health(bot))
