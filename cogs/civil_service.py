"""Dravia State Bot - Civil Service System"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.calendar import stamp, to_dravian

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Grade salaries from Dravian law
GRADES = {
    "A": {"name": "Permanent Secretary", "salary": 3500, "grade": "A"},
    "B": {"name": "Director", "salary": 2800, "grade": "B"},
    "C": {"name": "Principal Officer", "salary": 2200, "grade": "C"},
    "D": {"name": "Senior Officer", "salary": 1800, "grade": "D"},
    "E": {"name": "Officer", "salary": 1400, "grade": "E"},
    "F": {"name": "Assistant Officer", "salary": 1000, "grade": "F"},
    "G": {"name": "Clerk", "salary": 700, "grade": "G"}
}

JOB_FAMILIES = [
    "Policy", "Finance and Revenue", "Law and Justice", "Public Works",
    "Agriculture", "Commerce", "Information and Culture", "Administration",
    "Health", "Education"
]

# Sample exam questions
EXAM_QUESTIONS = [
    {"q": "What is the currency of Dravia?", "a": "ovi"},
    {"q": "What is the capital of Dravia?", "a": "dravia"},
    {"q": "What is the tax rate for income 501-2000 Ovi?", "a": "3"},
    {"q": "How much is the daily UBI?", "a": "50"},
    {"q": "What year was Dravia founded?", "a": "2024"},
    {"q": "What is the highest civil service grade?", "a": "a"},
    {"q": "How much does a Grade G clerk earn per week?", "a": "700"},
    {"q": "What is the GST rate?", "a": "5"},
    {"q": "What is the bank interest rate on savings?", "a": "4"},
    {"q": "How many job families are there?", "a": "10"}
]

class CivilService(commands.Cog):
    """Civil service commands for Dravia."""
    
    cs_group = app_commands.Group(name="civilservice", description="Civil service commands")
    
    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)
    
    async def get_civil_servant(self, user_id: str) -> dict:
        """Get civil servant record."""
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM civil_servants WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def create_civil_servant(self, user_id: str, grade: str, job_family: str):
        """Create civil servant record."""
        async with await self.db.get_connection() as db:
            await db.execute(
                """INSERT INTO civil_servants (user_id, grade, job_family, hire_date, status, probation_until)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, grade, job_family, datetime.now().isoformat(), "probation", 
                 (datetime.now() + timedelta(days=90)).isoformat())
            )
            await db.commit()
    
    # (Stub command replaced by the /civilservice command group)
    @cs_group.command(name="apply", description="Apply for civil service position")
    @app_commands.describe(
        grade="Desired grade (G=lowest, A=highest)",
        job_family="Job family"
    )
    @app_commands.choices(grade=[
        app_commands.Choice(name="Grade G - Clerk (700 Ovi/week)", value="G"),
        app_commands.Choice(name="Grade F - Assistant Officer (1000 Ovi/week)", value="F"),
        app_commands.Choice(name="Grade E - Officer (1400 Ovi/week)", value="E"),
        app_commands.Choice(name="Grade D - Senior Officer (1800 Ovi/week)", value="D"),
        app_commands.Choice(name="Grade C - Principal Officer (2200 Ovi/week)", value="C"),
        app_commands.Choice(name="Grade B - Director (2800 Ovi/week)", value="B"),
        app_commands.Choice(name="Grade A - Permanent Secretary (3500 Ovi/week)", value="A")
    ])
    async def apply_civil_service(self, interaction: discord.Interaction, grade: str, job_family: str):
        """Apply for civil service."""
        user_id = str(interaction.user.id)
        
        # Check if already employed
        existing = await self.get_civil_servant(user_id)
        if existing:
            embed = discord.Embed(
                title="⚠️ Already Employed",
                description=f"You are already a **{existing['grade']}** in **{existing['job_family']}**.",
                color=COLOR_GOLD
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Validate job family
        if job_family not in JOB_FAMILIES:
            await interaction.response.send_message(
                f"❌ Invalid job family. Choose from: {', '.join(JOB_FAMILIES)}",
                ephemeral=True
            )
            return
        
        # Create application (auto-approved for now)
        await self.create_civil_servant(user_id, grade, job_family)
        
        grade_info = GRADES[grade]
        
        embed = discord.Embed(
            title="✅ Application Approved!",
            description=f"Welcome to the Dravian Civil Service!",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Grade", value=f"**{grade}** - {grade_info['name']}", inline=True)
        embed.add_field(name="Department", value=f"**{job_family}**", inline=True)
        embed.add_field(name="Salary", value=f"🪙 **{grade_info['salary']}**/week", inline=True)
        embed.add_field(name="Status", value="**Probation** (3 months)", inline=True)
        embed.set_footer(text="Ministry of Administration | Republic of Dravia")
        
        await interaction.response.send_message(embed=embed)
    
    @cs_group.command(name="status", description="Check your civil service status")
    async def civil_status(self, interaction: discord.Interaction):
        """Check civil service status."""
        user_id = str(interaction.user.id)
        servant = await self.get_civil_servant(user_id)
        
        if not servant:
            embed = discord.Embed(
                title="❌ Not Employed",
                description="You are not in the civil service. Use `/civilservice apply` to apply!",
                color=COLOR_CRIMSON
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        grade_info = GRADES[servant["grade"]]
        status = servant["status"]
        
        # Check probation
        if status == "probation":
            prob_end = datetime.fromisoformat(servant["probation_until"])
            days_left = (prob_end - datetime.now()).days
            status = f"Probation ({days_left} days left)"
        
        embed = discord.Embed(
            title="🏛️ Civil Service Status",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Grade", value=f"**{servant['grade']}** - {grade_info['name']}", inline=True)
        embed.add_field(name="Department", value=servant["job_family"], inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Hire Date", value=stamp(servant["hire_date"], "%d %B %Y"), inline=True)
        embed.set_footer(text="Ministry of Administration")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @cs_group.command(name="salary", description="Check your salary and payday")
    async def salary_info(self, interaction: discord.Interaction):
        """Check salary info."""
        user_id = str(interaction.user.id)
        servant = await self.get_civil_servant(user_id)
        
        if not servant:
            await interaction.response.send_message("❌ You are not employed in civil service.", ephemeral=True)
            return
        
        grade_info = GRADES[servant["grade"]]
        
        # Calculate next payday (Friday)
        now = datetime.now()
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7
        next_payday = now + timedelta(days=days_until_friday)
        
        embed = discord.Embed(
            title="💰 Salary Information",
            color=COLOR_GOLD
        )
        embed.add_field(name="Grade", value=f"**{servant['grade']}** - {grade_info['name']}", inline=True)
        embed.add_field(name="Weekly Salary", value=f"🪙 **{grade_info['salary']:,}**", inline=True)
        embed.add_field(name="Annual Salary", value=f"🪙 **{grade_info['salary'] * 52:,}**", inline=True)
        embed.add_field(name="Next Payday", value=to_dravian(next_payday).strftime("%A, %d %B %Y"), inline=True)
        embed.set_footer(text="Ministry of Finance | Paydays every Friday")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @cs_group.command(name="list", description="List open positions")
    async def list_positions(self, interaction: discord.Interaction):
        """List open civil service positions."""
        embed = discord.Embed(
            title="📋 Open Positions",
            description="Current civil service vacancies",
            color=COLOR_ACCENT
        )
        
        for grade, info in GRADES.items():
            embed.add_field(
                name=f"Grade {grade} - {info['name']}",
                value=f"🪙 **{info['salary']}**/week",
                inline=True
            )
        
        embed.add_field(
            name="Job Families",
            value="\n".join(JOB_FAMILIES),
            inline=False
        )
        
        embed.set_footer(text="Apply with /civilservice apply")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Admin commands
    @cs_group.command(name="approve", description="Approve a civil servant (Admin)")
    @app_commands.describe(user="User to approve", grade="Grade", department="Department")
    @app_commands.default_permissions(manage_guild=True)
    async def approve_civil(self, interaction: discord.Interaction, user: discord.User, grade: str, department: str):
        """Approve civil servant."""
        user_id = str(user.id)
        
        await self.create_civil_servant(user_id, grade, department)
        
        await interaction.response.send_message(
            f"✅ {user.display_name} approved as Grade {grade} in {department}",
            ephemeral=True
        )
    
    @cs_group.command(name="promote", description="Promote a civil servant (Admin)")
    @app_commands.describe(user="User to promote", new_grade="New grade")
    @app_commands.default_permissions(manage_guild=True)
    async def promote_civil(self, interaction: discord.Interaction, user: discord.User, new_grade: str):
        """Promote civil servant."""
        user_id = str(user.id)
        
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE civil_servants SET grade = ? WHERE user_id = ?",
                (new_grade, user_id)
            )
            await db.commit()
        
        grade_info = GRADES[new_grade]
        await interaction.response.send_message(
            f"✅ {user.display_name} promoted to Grade {new_grade} ({grade_info['name']})",
            ephemeral=True
        )
    
    @cs_group.command(name="dismiss", description="Dismiss a civil servant (Admin)")
    @app_commands.describe(user="User to dismiss", reason="Reason")
    @app_commands.default_permissions(manage_guild=True)
    async def dismiss_civil(self, interaction: discord.Interaction, user: discord.User, reason: str):
        """Dismiss civil servant."""
        user_id = str(user.id)
        
        async with await self.db.get_connection() as db:
            await db.execute("DELETE FROM civil_servants WHERE user_id = ?", (user_id,))
            await db.commit()
        
        await interaction.response.send_message(
            f"❌ {user.display_name} dismissed from civil service. Reason: {reason}",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(CivilService(bot))