"""Dravia State Bot - Police Academy"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os
import random
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.logger import audit_log, police_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

PASS_MARK = 70  # percent

ACADEMY_EXAM = [
    ("What is the Dravian currency?", ["Ovi", "Dollar", "Euro", "Gold"], 0),
    ("What does 10-4 mean?", ["Acknowledged", "Emergency", "Out of service", "Pursuit"], 0),
    ("Maximum daily gambling loss limit?", ["200 Ovi", "500 Ovi", "1,000 Ovi", "No limit"], 0),
    ("Who oversees police complaints?", ["IPOC", "The Curia alone", "The Mayor", "No one"], 0),
    ("What is the income tax rate for 501-2,000 Ovi?", ["0%", "3%", "5%", "10%"], 1),
    ("Miranda rights must be given before...", ["Questioning", "Pat-down", "Radio call", "Shift end"], 0),
]

MODULES = ["Patrol Procedures", "Criminal Law", "Traffic", "Report Writing", "Community Relations", "Use of Force"]

PRACTICALS = ["Suspect apprehension", "Vehicle stop", "Evidence handling", "Crowd control"]
FIREARMS_STAGES = ["Safety", "Marksmanship", "Rapid fire", "Low light"]

class PoliceAcademy(commands.Cog):
    """Dravia Police Academy commands."""
    
    academy_group = app_commands.Group(name="academy", description="Dravia Police Academy")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    async def get_record(self, user_id: str):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM academy WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def ensure_record(self, user_id: str) -> dict:
        record = await self.get_record(user_id)
        if not record:
            async with await self.db.get_connection() as db:
                await db.execute(
                    "INSERT INTO academy (user_id, applied_at) VALUES (?, ?)",
                    (user_id, datetime.now().isoformat()),
                )
                await db.commit()
            record = await self.get_record(user_id)
        return record

    async def update(self, user_id: str, **fields):
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        async with await self.db.get_connection() as db:
            await db.execute(f"UPDATE academy SET {sets} WHERE user_id = ?", (*fields.values(), user_id))
            await db.commit()

    @academy_group.command(name="apply", description="Apply to the Police Academy")
    async def academy_apply(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        record = await self.get_record(user_id)
        if record and record["status"] in ("applicant", "cadet", "graduated"):
            await interaction.response.send_message(
                f"⚠️ You already have an academy record (**{record['status']}**).", ephemeral=True
            )
            return

        await self.ensure_record(user_id)
        embed = discord.Embed(
            title="🎓 Academy Application Received",
            description="Welcome, candidate. Take the entrance exam with `/academy exam`.",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Next Step", value="`/academy exam` — 6 questions, 70% to pass", inline=False)
        embed.set_footer(text="Dravia Police Academy")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @academy_group.command(name="exam", description="Take the academy entrance exam (6 questions)")
    async def academy_exam(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await self.ensure_record(user_id)

        questions = random.sample(ACADEMY_EXAM, len(ACADEMY_EXAM))[:6]

        # Sequential multiple-choice exam, one question at a time
        score = 0
        await interaction.response.send_message(
            f"📝 **Police Academy Entrance Exam** — 6 questions, pass mark {PASS_MARK}%\nAnswer within 60 seconds each.",
            ephemeral=True,
        )
        for idx, (q_text, options, correct_idx) in enumerate(questions, 1):
            options_view = discord.ui.View(timeout=60)

            def make_callback(idx):
                async def callback(btn_interaction: discord.Interaction):
                    if btn_interaction.user.id != interaction.user.id:
                        await btn_interaction.response.send_message("Not your exam.", ephemeral=True)
                        return
                    nonlocal score
                    if idx == correct_idx:
                        score += 1
                        await btn_interaction.response.send_message("✅ Correct!", ephemeral=True)
                    else:
                        await btn_interaction.response.send_message(
                            f"❌ Wrong. Correct answer: **{options[correct_idx]}**", ephemeral=True
                        )
                    options_view.stop()
                return callback

            for i, opt in enumerate(options):
                btn = discord.ui.Button(label=opt, style=discord.ButtonStyle.secondary, row=i // 2)
                btn.callback = make_callback(i)
                options_view.add_item(btn)

            msg = await interaction.followup.send(f"**Q{idx}.** {q_text}", view=options_view, wait=True)
            await options_view.wait()

        pct = round(score / len(questions) * 100)
        passed = pct >= PASS_MARK

        if passed:
            await self.update(user_id, status="cadet", exam_score=pct)
            police_log.info("Academy exam passed by %s: %s%%", user_id, pct)
            embed = discord.Embed(
                title="✅ Academy Exam PASSED",
                description=f"Score: **{pct}%** — You are now a **Cadet**!\nContinue with `/academy train`.",
                color=COLOR_ACCENT,
            )
        else:
            police_log.info("Academy exam failed by %s: %s%%", user_id, pct)
            embed = discord.Embed(
                title="❌ Academy Exam FAILED",
                description=f"Score: **{pct}%** — {PASS_MARK}% required. One retake per 30 days.",
                color=COLOR_CRIMSON,
            )
        embed.add_field(name="Correct Answers", value=f"{score}/{len(questions)}", inline=True)
        await interaction.followup.send(embed=embed)

    @academy_group.command(name="train", description="Complete a training module")
    @app_commands.choices(module=[app_commands.Choice(name=m, value=m) for m in MODULES])
    async def academy_train(self, interaction: discord.Interaction, module: str):
        user_id = str(interaction.user.id)
        record = await self.ensure_record(user_id)
        if record["status"] not in ("cadet", "applicant"):
            await interaction.response.send_message("❌ You are not an academy cadet.", ephemeral=True)
            return

        done = [m for m in (record["modules_done"] or "").split(",") if m]
        if module in done:
            await interaction.response.send_message(f"⚠️ You already completed **{module}**.", ephemeral=True)
            return
        done.append(module)
        await self.update(user_id, modules_done=",".join(done))

        embed = discord.Embed(
            title="📚 Module Completed",
            description=f"**{module}** — {len(done)}/{len(MODULES)} modules complete",
            color=COLOR_ACCENT,
        )
        embed.set_footer(text="Dravia Police Academy")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @academy_group.command(name="test", description="Take an academy test")
    @app_commands.choices(kind=[
        app_commands.Choice(name="Written Exam", value="written"),
        app_commands.Choice(name="Practical Exam", value="practical"),
        app_commands.Choice(name="Firearms Qualification", value="firearms"),
    ])
    async def academy_test(self, interaction: discord.Interaction, kind: str):
        user_id = str(interaction.user.id)
        record = await self.ensure_record(user_id)
        if record["status"] != "cadet":
            await interaction.response.send_message("❌ Only cadets may sit tests.", ephemeral=True)
            return

        if kind == "written":
            score = random.randint(55, 100)
            passed = score >= PASS_MARK
            await self.update(user_id, written_test=score)
            detail = f"Written exam score: **{score}%**"
        elif kind == "practical":
            stages = random.sample(PRACTICALS, len(PRACTICALS))
            passed = random.random() > 0.2
            await self.update(user_id, practical_test=1 if passed else 0)
            detail = "Practical stages: " + ", ".join(stages[: random.randint(2, 4)])
        else:
            stages = random.sample(FIREARMS_STAGES, len(FIREARMS_STAGES))
            passed = random.random() > 0.25
            await self.update(user_id, firearms_test=1 if passed else 0)
            detail = "Firearms stages: " + ", ".join(stages)

        police_log.info("Academy %s test by %s: passed=%s", kind, user_id, passed)
        embed = discord.Embed(
            title=("✅ Test PASSED" if passed else "❌ Test FAILED"),
            description=detail,
            color=COLOR_ACCENT if passed else COLOR_CRIMSON,
        )
        embed.set_footer(text="Dravia Police Academy")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @academy_group.command(name="status", description="View your training progress")
    async def academy_status(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        record = await self.get_record(user_id)
        if not record:
            await interaction.response.send_message(
                "❌ No academy record. Use `/academy apply` first.", ephemeral=True
            )
            return

        done = [m for m in (record["modules_done"] or "").split(",") if m]
        embed = discord.Embed(title="🎓 Academy Status", color=COLOR_ACCENT)
        embed.add_field(name="Status", value=record["status"].title(), inline=True)
        embed.add_field(name="Entrance Score", value=f"{record['exam_score']}%" if record["exam_score"] else "—", inline=True)
        embed.add_field(name="Modules", value=f"{len(done)}/{len(MODULES)}", inline=True)
        embed.add_field(name="Written", value="✅" if record["written_test"] >= PASS_MARK else "❌", inline=True)
        embed.add_field(name="Practical", value="✅" if record["practical_test"] else "❌", inline=True)
        embed.add_field(name="Firearms", value="✅" if record["firearms_test"] else "❌", inline=True)
        embed.add_field(
            name="Remaining Modules",
            value=", ".join(m for m in MODULES if m not in done) or "None",
            inline=False,
        )
        embed.set_footer(text="Dravia Police Academy")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @academy_group.command(name="graduate", description="Graduate and receive your rank")
    async def academy_graduate(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        record = await self.get_record(user_id)
        if not record or record["status"] != "cadet":
            await interaction.response.send_message("❌ You are not a cadet.", ephemeral=True)
            return

        done = [m for m in (record["modules_done"] or "").split(",") if m]
        missing = []
        if len(done) < len(MODULES):
            missing.append(f"{len(MODULES) - len(done)} training modules")
        if record["written_test"] < PASS_MARK:
            missing.append("written exam")
        if not record["practical_test"]:
            missing.append("practical exam")
        if not record["firearms_test"]:
            missing.append("firearms qualification")

        if missing:
            await interaction.response.send_message(
                f"❌ Cannot graduate. Outstanding: **{', '.join(missing)}**", ephemeral=True
            )
            return

        await self.update(user_id, status="graduated", graduated_at=datetime.now().isoformat())

        # Create police record as Patrol Officer I
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT OR REPLACE INTO police (user_id, rank, join_date, status, arrests) VALUES (?, ?, ?, 'active', 0)",
                (user_id, "Patrol Officer I", datetime.now().isoformat()),
            )
            await db.commit()

        police_log.info("Academy graduate: %s -> Patrol Officer I", user_id)
        embed = discord.Embed(
            title="🎓🎓 GRADUATED!",
            description=f"{interaction.user.mention} is commissioned as a **Patrol Officer I** of the Dravia Police Force!",
            color=COLOR_GOLD,
        )
        embed.add_field(name="Next Steps", value="Take the oath with `/academy oath`, then `/police duty_start`.", inline=False)
        embed.set_footer(text="Dravia Police Academy | To Protect and Serve")
        await interaction.response.send_message(embed=embed)

    @academy_group.command(name="oath", description="Swear the Police Pledge")
    async def academy_oath(self, interaction: discord.Interaction):
        oath = (
            "**The Police Pledge**\n\n"
            "\"I solemnly swear to uphold the law of the Republic of Dravia, "
            "to protect life and property, to serve with integrity and impartiality, "
            "to respect the rights of every citizen, and to answer to the people "
            "through the Independent Police Oversight Commission. So help me, Dravia.\""
        )
        embed = discord.Embed(title="🤝 The Police Pledge", description=oath, color=COLOR_GOLD)
        embed.set_footer(text="Republic of Dravia | De Custodia Publica Draviae")
        await interaction.response.send_message(embed=embed)
        police_log.info("Oath sworn by %s", interaction.user.id)


async def setup(bot):
    await bot.add_cog(PoliceAcademy(bot))
