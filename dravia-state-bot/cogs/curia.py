"""Dravia State Bot - Curia (Legislative) System"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.checks import requires_curial
from utils.logger import audit_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

VOTE_THRESHOLD = 50  # % yes needed to enact (simple majority of votes cast)

class Curia(commands.Cog):
    """Curia legislative commands."""
    
    curia_group = app_commands.Group(name="curia", description="Legislative commands")
    audit_group = app_commands.Group(name="audit", description="Curial audit commands")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    async def get_law(self, law_id: int):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM laws WHERE id = ?", (law_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    @curia_group.command(name="propose", description="Propose a new law")
    @app_commands.describe(law_name="Short title of the law", text="Full text of the law")
    async def curia_propose(self, interaction: discord.Interaction, law_name: str, text: str):
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO laws (law_name, law_text, proposed_by, proposed_at) VALUES (?, ?, ?, ?)",
                (law_name, text, user_id, datetime.now().isoformat()),
            )
            law_id = cursor.lastrowid
            await db.commit()

        audit_log.info("Law #%s proposed by %s: %s", law_id, user_id, law_name)
        embed = discord.Embed(
            title="📜 Law Proposed",
            description=f"**{law_name}** (#{law_id})",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Text", value=text[:1000], inline=False)
        embed.add_field(name="Status", value="Open for debate and vote", inline=True)
        embed.add_field(name="Vote", value=f"`/curia vote {law_id} yes|no|abstain`", inline=False)
        embed.set_footer(text="Republic of Dravia | Curia Draviae")
        await interaction.response.send_message(embed=embed)

    @curia_group.command(name="vote", description="Vote on a law")
    @app_commands.describe(law_id="Law number", choice="Your vote")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Yes", value="yes"),
        app_commands.Choice(name="No", value="no"),
        app_commands.Choice(name="Abstain", value="abstain"),
    ])
    async def curia_vote(self, interaction: discord.Interaction, law_id: int, choice: str):
        user_id = str(interaction.user.id)
        law = await self.get_law(law_id)
        if not law:
            await interaction.response.send_message("❌ Law not found.", ephemeral=True)
            return
        if law["status"] not in ("proposed", "debate"):
            await interaction.response.send_message("❌ Voting is closed on this law.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            # Remove previous vote if any (one vote per user)
            async with db.execute(
                "SELECT vote FROM law_votes WHERE law_id = ? AND user_id = ?", (law_id, user_id)
            ) as cursor:
                previous = await cursor.fetchone()

            if previous:
                prev = previous[0]
                await db.execute(
                    f"UPDATE laws SET votes_{prev} = votes_{prev} - 1 WHERE id = ?", (law_id,)
                )

            await db.execute(
                "INSERT INTO law_votes (law_id, user_id, vote) VALUES (?, ?, ?) "
                "ON CONFLICT(law_id, user_id) DO UPDATE SET vote = excluded.vote",
                (law_id, user_id, choice),
            )
            await db.execute(
                f"UPDATE laws SET votes_{choice} = votes_{choice} + 1 WHERE id = ?", (law_id,)
            )

            # Check enactment
            async with db.execute(
                "SELECT votes_yes, votes_no, votes_abstain FROM laws WHERE id = ?", (law_id,)
            ) as cursor:
                y, n, a = await cursor.fetchone()

            total = y + n + a
            enacted = False
            if total >= 3 and y > n and (y / total * 100) >= VOTE_THRESHOLD:
                await db.execute(
                    "UPDATE laws SET status = 'enacted', enacted_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), law_id),
                )
                enacted = True
            await db.commit()

        embed = discord.Embed(
            title="🗳️ Vote Recorded" + (" — LAW ENACTED!" if enacted else ""),
            description=f"You voted **{choice.upper()}** on law #{law_id} *{law['law_name']}*",
            color=COLOR_GOLD if enacted else COLOR_ACCENT,
        )
        embed.add_field(name="Yes", value=str(y), inline=True)
        embed.add_field(name="No", value=str(n), inline=True)
        embed.add_field(name="Abstain", value=str(a), inline=True)
        if enacted:
            embed.add_field(name="Status", value="✅ Enacted into law", inline=False)
            audit_log.info("Law #%s ENACTED", law_id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @curia_group.command(name="status", description="Check a law's status")
    @app_commands.describe(law_id="Law number")
    async def curia_status(self, interaction: discord.Interaction, law_id: int):
        law = await self.get_law(law_id)
        if not law:
            await interaction.response.send_message("❌ Law not found.", ephemeral=True)
            return

        total = law["votes_yes"] + law["votes_no"] + law["votes_abstain"]
        pct = (law["votes_yes"] / total * 100) if total else 0
        embed = discord.Embed(title=f"📜 Law #{law_id}: {law['law_name']}", color=COLOR_ACCENT)
        embed.add_field(name="Status", value=law["status"].title(), inline=True)
        embed.add_field(name="Proposed By", value=f"<@{law['proposed_by']}>", inline=True)
        embed.add_field(name="Yes / No / Abstain", value=f"**{law['votes_yes']}** / **{law['votes_no']}** / **{law['votes_abstain']}**", inline=True)
        embed.add_field(name="Support", value=f"**{pct:.0f}%** ({total} votes cast)", inline=True)
        if law["enacted_at"]:
            embed.add_field(name="Enacted", value=law["enacted_at"][:10], inline=True)
        embed.add_field(name="Text", value=(law["law_text"] or "")[:1000], inline=False)
        await interaction.response.send_message(embed=embed)

    @curia_group.command(name="debate", description="Open debate on a law")
    @app_commands.describe(law_id="Law number")
    async def curia_debate(self, interaction: discord.Interaction, law_id: int):
        law = await self.get_law(law_id)
        if not law:
            await interaction.response.send_message("❌ Law not found.", ephemeral=True)
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE laws SET status = 'debate' WHERE id = ?", (law_id,))
            await db.commit()

        embed = discord.Embed(
            title="🎙️ Debate Opened",
            description=f"Floor debate on **{law['law_name']}** (#{law_id}) is now open.",
            color=COLOR_ACCENT,
        )
        embed.set_footer(text="Republic of Dravia | Curia Draviae")
        await interaction.response.send_message(embed=embed)

    @curia_group.command(name="summon", description="Summon a minister to the Curia")
    @app_commands.describe(minister="Minister to summon", reason="Reason for the summons")
    async def curia_summon(self, interaction: discord.Interaction, minister: discord.Member, reason: str):
        embed = discord.Embed(
            title="⚖️ Summons Issued",
            description=f"{minister.mention} is summoned before the Curia.\n**Reason:** {reason[:500]}",
            color=COLOR_CRIMSON,
        )
        embed.set_footer(text="Republic of Dravia | Curia Draviae")
        await interaction.response.send_message(embed=embed)
        try:
            await minister.send(f"⚖️ You have been summoned before the Curia: {reason[:500]}")
        except Exception:
            pass

    @curia_group.command(name="committee", description="Form a committee")
    @app_commands.describe(name="Committee name", purpose="Committee purpose")
    @requires_curial
    async def curia_committee(self, interaction: discord.Interaction, name: str, purpose: str):
        embed = discord.Embed(
            title="🏛️ Committee Formed",
            description=f"**{name}**\nPurpose: {purpose[:500]}",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Members", value="Appointed by the Curia", inline=True)
        await interaction.response.send_message(embed=embed)

    @curia_group.command(name="report", description="View the legislative session report")
    @requires_curial
    async def curia_report(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT COUNT(*) FROM laws") as cursor:
                total = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM laws WHERE status = 'enacted'") as cursor:
                enacted = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM laws WHERE status IN ('proposed', 'debate')") as cursor:
                pending = (await cursor.fetchone())[0]

        embed = discord.Embed(title="📊 Legislative Session Report", color=COLOR_GOLD)
        embed.add_field(name="Laws Proposed", value=f"**{total}**", inline=True)
        embed.add_field(name="Enacted", value=f"**{enacted}**", inline=True)
        embed.add_field(name="Pending", value=f"**{pending}**", inline=True)
        embed.set_footer(text="Republic of Dravia | Curia Draviae")
        await interaction.response.send_message(embed=embed)

    @curia_group.command(name="register", description="Register of all laws in force")
    async def curia_register(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, law_name, enacted_at FROM laws WHERE status = 'enacted' ORDER BY id DESC LIMIT 10"
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title="📚 Register of Laws in Force", color=COLOR_GOLD)
        if not rows:
            embed.description = "No laws enacted yet."
        else:
            for r in rows:
                embed.add_field(
                    name=f"#{r['id']} {r['law_name']}",
                    value=f"Enacted {(r['enacted_at'] or '')[:10]}",
                    inline=False,
                )
        embed.set_footer(text="Republic of Dravia | Curia Draviae")
        await interaction.response.send_message(embed=embed)

    # --- Audit commands (Curial only) ---

    @audit_group.command(name="police", description="Audit police activity")
    @requires_curial
    async def audit_police(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT COUNT(*) FROM police") as cursor:
                officers = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM criminals") as cursor:
                offenders = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM ia_cases") as cursor:
                ia = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM ia_cases WHERE status = 'open'") as cursor:
                open_ia = (await cursor.fetchone())[0]

        audit_log.info("Police audit by %s", interaction.user.id)
        embed = discord.Embed(title="🔍 Police Audit", color=COLOR_ACCENT)
        embed.add_field(name="Officers", value=f"**{officers}**", inline=True)
        embed.add_field(name="Registered Offenders", value=f"**{offenders}**", inline=True)
        embed.add_field(name="IA Cases", value=f"**{ia}** ({open_ia} open)", inline=True)
        embed.set_footer(text="Republic of Dravia | Curia oversight")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @audit_group.command(name="economy", description="Audit economic health")
    @requires_curial
    async def audit_economy(self, interaction: discord.Interaction):
        stats = await self.db.get_economy_stats()
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type LIKE '%tax%'") as cursor:
                tax_flow = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM businesses WHERE is_active = 1") as cursor:
                businesses = (await cursor.fetchone())[0]

        audit_log.info("Economy audit by %s", interaction.user.id)
        embed = discord.Embed(title="📈 Economic Audit", color=COLOR_GOLD)
        embed.add_field(name="Money Supply", value=f"🪙 **{stats['total_money'] or 0:,}**", inline=True)
        embed.add_field(name="Citizens", value=f"**{stats['total_users']}**", inline=True)
        embed.add_field(name="Average Wealth", value=f"🪙 **{stats['avg_balance'] or 0:.0f}**", inline=True)
        embed.add_field(name="Tax Flow (logged)", value=f"🪙 **{tax_flow:,}**", inline=True)
        embed.add_field(name="Active Businesses", value=f"**{businesses}**", inline=True)
        embed.set_footer(text="Multiplier effect: 1 Ovi spent ≈ 1.5x economic activity")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @audit_group.command(name="business", description="Audit a business")
    @app_commands.describe(name="Business name")
    @requires_curial
    async def audit_business(self, interaction: discord.Interaction, name: str):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM businesses WHERE lower(name) = lower(?)", (name,)
            ) as cursor:
                biz = await cursor.fetchone()
        if not biz:
            await interaction.response.send_message("❌ Business not found.", ephemeral=True)
            return

        audit_log.info("Business audit: %s by %s", name, interaction.user.id)
        embed = discord.Embed(title=f"🔍 Business Audit: {biz['name']}", color=COLOR_ACCENT)
        embed.add_field(name="Owner", value=f"<@{biz['owner_id']}>", inline=True)
        embed.add_field(name="License", value=biz["license_type"], inline=True)
        embed.add_field(name="Status", value="Active" if biz["is_active"] else "Closed", inline=True)
        embed.add_field(name="Facility Tier", value=str(biz["facility_tier"]), inline=True)
        embed.add_field(name="Registered", value=(biz["registered_at"] or "")[:10], inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @audit_group.command(name="government", description="Audit government spending")
    @requires_curial
    async def audit_government(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT type, COALESCE(SUM(amount),0) as total FROM transactions WHERE from_user = 'system' GROUP BY type ORDER BY total DESC LIMIT 8"
            ) as cursor:
                rows = await cursor.fetchall()

        audit_log.info("Government spending audit by %s", interaction.user.id)
        embed = discord.Embed(title="🏛️ Government Spending Audit", color=COLOR_GOLD)
        if not rows:
            embed.description = "No government outflows recorded."
        else:
            for t, total in rows:
                embed.add_field(name=t.replace("_", " ").title(), value=f"🪙 **{total:,}**", inline=True)
        embed.set_footer(text="Republic of Dravia | Curia oversight")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @audit_group.command(name="citizen", description="Audit a citizen's tax compliance")
    @app_commands.describe(user="Citizen to audit")
    @requires_curial
    async def audit_citizen(self, interaction: discord.Interaction, user: discord.User):
        user_id = str(user.id)
        await self.db.create_user(user_id)
        record = await self.db.get_user(user_id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM taxes WHERE user_id = ? AND paid = 1", (user_id,)
            ) as cursor:
                paid = (await cursor.fetchone())[0]
            async with db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM taxes WHERE user_id = ? AND paid = 0", (user_id,)
            ) as cursor:
                owed = (await cursor.fetchone())[0]

        audit_log.info("Citizen tax audit: %s by %s", user_id, interaction.user.id)
        embed = discord.Embed(title=f"🔎 Tax Compliance: {user.display_name}", color=COLOR_ACCENT)
        embed.add_field(name="Total Earned", value=f"🪙 **{record['total_earned'] if record else 0:,}**", inline=True)
        embed.add_field(name="Tax Paid", value=f"🪙 **{paid:,}**", inline=True)
        embed.add_field(name="Tax Owed", value=f"🪙 **{owed:,}**", inline=True)
        embed.add_field(
            name="Compliance",
            value="✅ Compliant" if owed == 0 else "⚠️ Outstanding liability",
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Curia(bot))
