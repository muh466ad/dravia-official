"""Dravia State Bot - Education (Universities & Courses)

Tables: `universities`, `courses`, `student_records`. Professors found
institutions and offer courses, citizens enrol (paying tuition per week of
study), and a passing grade pays a completion bonus. Dates render through
`stamp()`.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, ovi, success, warning
from utils.checks import requires_professor
from utils.validation import text, whole_number

UNI_TYPES = ["Technical", "Liberal Arts", "Medical", "Law"]
GRADES = ["A+", "A", "B", "C", "D", "F"]

#: Founding a university / per week of tuition / completion bonus.
FOUNDER_COST = 5000
TUITION_PER_WEEK = 100
COMPLETION_BONUS = 250


class Education(DraviaCog):
    """Ministry of Education commands."""

    group_name = "economy"
    education_group = app_commands.Group(
        name="education", description="Universities, courses and transcripts"
    )

    # ------------------------------------------------------------ helpers
    async def _get_course(self, course_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT course_id, university_id, name, professor_id, duration_weeks "
                "FROM courses WHERE course_id = ?", (course_id,)
            ) as cur:
                row = await cur.fetchone()
        return row if row else None

    # ------------------------------------------------------------ commands
    @education_group.command(name="found", description="Found a university (Professor, 5,000 Ovi)")
    @app_commands.describe(name="Institution name", uni_type="Specialisation")
    @app_commands.choices(uni_type=[app_commands.Choice(name=t, value=t) for t in UNI_TYPES])
    @handles_validation
    @requires_professor
    async def education_found(self, interaction: discord.Interaction, name: str,
                              uni_type: str = "Technical"):
        name = text(name, field="Name", maximum=80)
        uni_type = uni_type if uni_type in UNI_TYPES else UNI_TYPES[0]
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT 1 FROM universities WHERE name = ? COLLATE NOCASE", (name,)
            ) as cur:
                if await cur.fetchone():
                    await self.fail(interaction, f"**{name}** already exists.")
                    return
        if not await self.debit(user_id, FOUNDER_COST, "education", f"Founded {name}"):
            await self.fail(interaction,
                            f"Founding a university costs {ovi(FOUNDER_COST)} — you cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO universities (name, type, founded_at) VALUES (?, ?, date('now'))",
                (name, uni_type),
            )
            await db.commit()
        log_action("education", "found", user_id, name=name, uni_type=uni_type)
        embed = success("Charter granted", f"**{name}** ({uni_type}) may now teach.")
        embed.add_field(name="Cost", value=ovi(FOUNDER_COST))
        embed.add_field(name="Next", value="Offer courses with `/education offer`.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @education_group.command(name="universities", description="Every chartered institution")
    async def education_universities(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT university_id, name, type, founded_at FROM universities "
                "ORDER BY university_id LIMIT 25"
            ) as cur:
                rows = await cur.fetchall()
            async with db.execute(
                "SELECT university_id, COUNT(*) FROM courses GROUP BY university_id"
            ) as cur:
                counts = dict(await cur.fetchall())
        embed = DraviaEmbed(title="🎓 Dravian Institutions", color=COLOR_GOLD)
        if not rows:
            embed.description = "No universities yet. Professors found one with `/education found`."
        for uni_id, name, uni_type, founded_at in rows:
            embed.add_field(
                name=f"#{uni_id} {name}",
                value=f"{uni_type} · {counts.get(uni_id, 0)} course(s) · "
                      f"chartered {stamp(founded_at) if founded_at else '—'}",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @education_group.command(name="offer", description="Offer a course (Professor)")
    @app_commands.describe(university_id="Where it is taught", name="Course name",
                           duration_weeks="How long it runs")
    @handles_validation
    @requires_professor
    async def education_offer(self, interaction: discord.Interaction, university_id: int,
                              name: str, duration_weeks: int = 4):
        name = text(name, field="Course name", maximum=80)
        duration_weeks = whole_number(duration_weeks, field="Duration", minimum=1, maximum=52)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT 1 FROM universities WHERE university_id = ?", (university_id,)
            ) as cur:
                if not await cur.fetchone():
                    await self.fail(interaction, f"No university #{university_id} exists.")
                    return
            await db.execute(
                "INSERT INTO courses (university_id, name, professor_id, duration_weeks) "
                "VALUES (?, ?, ?, ?)",
                (university_id, name, str(interaction.user.id), duration_weeks),
            )
            await db.commit()
            async with db.execute("SELECT MAX(course_id) FROM courses") as cur:
                course_id = (await cur.fetchone())[0]
        log_action("education", "offer", str(interaction.user.id),
                   course=course_id, name=name)
        embed = success("Course offered", f"**{name}** runs {duration_weeks} week(s).")
        embed.add_field(name="Course ID", value=f"#{course_id}")
        embed.add_field(name="Tuition", value=ovi(duration_weeks * TUITION_PER_WEEK))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @education_group.command(name="courses", description="Courses at an institution")
    @app_commands.describe(university_id="Institution to browse")
    async def education_courses(self, interaction: discord.Interaction, university_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT course_id, name, professor_id, duration_weeks FROM courses "
                "WHERE university_id = ? ORDER BY course_id LIMIT 15",
                (university_id,),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title=f"🎓 Courses (#{university_id})", color=COLOR_GOLD)
        if not rows:
            embed.description = "This institution offers no courses yet."
        for course_id, name, professor_id, weeks in rows:
            embed.add_field(
                name=f"#{course_id} {name}",
                value=f"{weeks} week(s) · {weeks * TUITION_PER_WEEK} Ovi · "
                      f"taught by <@{professor_id}>",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @education_group.command(name="enroll", description="Enrol in a course (pays tuition)")
    @app_commands.describe(course_id="Course to take")
    async def education_enroll(self, interaction: discord.Interaction, course_id: int):
        course = await self._get_course(course_id)
        if course is None:
            await self.fail(interaction, f"No course #{course_id} exists.")
            return
        user_id = str(interaction.user.id)
        tuition = course[4] * TUITION_PER_WEEK
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT 1 FROM student_records WHERE student_id = ? AND course_id = ?",
                (user_id, course_id),
            ) as cur:
                if await cur.fetchone():
                    await self.fail(interaction, f"You are already enrolled in course #{course_id}.")
                    return
            if not await self.debit(user_id, tuition, "education", f"Tuition: {course[2]}"):
                await self.fail(interaction,
                                f"Tuition is {ovi(tuition)} — you cannot afford it.")
                return
            await db.execute(
                "INSERT INTO student_records (student_id, course_id) VALUES (?, ?)",
                (user_id, course_id),
            )
            await db.commit()
        log_action("education", "enroll", user_id, course=course_id)
        embed = success("Enrolled", f"Welcome to **{course[2]}**.")
        embed.add_field(name="Tuition paid", value=ovi(tuition))
        embed.add_field(name="Next", value="Your Professor graduates you with `/education grade`.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @education_group.command(name="transcript", description="A student's record")
    @app_commands.describe(user="Whose transcript (defaults to you)")
    async def education_transcript(self, interaction: discord.Interaction,
                                   user: discord.Member = None):
        target = user or interaction.user
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT s.record_id, c.name, s.grade, s.completed_at "
                "FROM student_records s JOIN courses c ON c.course_id = s.course_id "
                "WHERE s.student_id = ? ORDER BY s.record_id DESC LIMIT 15",
                (str(target.id),),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title=f"🎓 Transcript — {target.display_name}", color=COLOR_GOLD)
        if not rows:
            embed.description = "No enrolments on file. `/education enroll` starts one."
        for record_id, course_name, grade, completed_at in rows:
            state = (f"grade {grade} · {stamp(completed_at)}" if grade
                     else "in progress")
            embed.add_field(name=f"{course_name}", value=f"{state} (record #{record_id})")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @education_group.command(name="grade", description="Issue a grade (the course's Professor)")
    @app_commands.describe(record_id="Student record", grade="Grade to award")
    @app_commands.choices(grade=[app_commands.Choice(name=g, value=g) for g in GRADES])
    @requires_professor
    async def education_grade(self, interaction: discord.Interaction, record_id: int,
                              grade: str):
        grade = grade if grade in GRADES else "F"
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT s.student_id, s.course_id, c.professor_id FROM student_records s "
                "JOIN courses c ON c.course_id = s.course_id WHERE s.record_id = ?",
                (record_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                await self.fail(interaction, f"No student record #{record_id} exists.")
                return
            student_id, course_id, professor_id = row
            if professor_id != user_id:
                await self.fail(interaction, "Only the course's professor may issue this grade.")
                return
            cur = await db.execute(
                "UPDATE student_records SET grade = ?, completed_at = date('now') "
                "WHERE record_id = ? AND grade IS NULL",
                (grade, record_id),
            )
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"Record #{record_id} is already graded.")
            return
        passed = grade != "F"
        if passed:
            await self.credit(student_id, COMPLETION_BONUS, "education",
                              f"Completed a course with {grade}")
        log_action("education", "grade", user_id, record=record_id, grade=grade)
        embed = success("Grade issued",
                        f"Record #{record_id}: **{grade}**" +
                        (f" — <@{student_id}> collected {ovi(COMPLETION_BONUS)}."
                         if passed else " — no bonus for a fail."))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @education_group.command(name="drop", description="Drop a course you have not finished")
    @app_commands.describe(record_id="Your student record")
    async def education_drop(self, interaction: discord.Interaction, record_id: int):
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            cur = await db.execute(
                "DELETE FROM student_records WHERE record_id = ? AND student_id = ? "
                "AND grade IS NULL",
                (record_id, user_id),
            )
            dropped = cur.rowcount
            await db.commit()
        if dropped != 1:
            await self.fail(interaction,
                            f"Record #{record_id} is not yours to drop (or it is already graded).")
            return
        log_action("education", "drop", user_id, record=record_id)
        embed = warning("Withdrawn", f"You dropped record #{record_id}. Tuition is not refunded.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Education(bot))
