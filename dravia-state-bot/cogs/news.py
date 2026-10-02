"""Dravia State Bot - News & Government Gazette"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.checks import requires_journalist
from utils.logger import audit_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

class News(commands.Cog):
    """News and Gazette commands."""
    
    news_group = app_commands.Group(name="news", description="Dravian Daily newspaper")
    gazette_group = app_commands.Group(name="gazette", description="Official Government Gazette")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    async def publish(self, title: str, content: str, author_id: str, kind: str) -> int:
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO news_articles (title, content, author_id, kind, published_at) VALUES (?, ?, ?, ?, ?)",
                (title, content, author_id, kind, datetime.now().isoformat()),
            )
            article_id = cursor.lastrowid
            await db.commit()
        return article_id

    @news_group.command(name="publish", description="Publish a news article (Journalist only)")
    @app_commands.describe(title="Headline", content="Article body")
    @requires_journalist
    async def news_publish(self, interaction: discord.Interaction, title: str, content: str):
        article_id = await self.publish(title, content, str(interaction.user.id), "news")
        embed = discord.Embed(
            title=f"📰 {title}",
            description=content[:4000],
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Article", value=f"#{article_id}", inline=True)
        embed.add_field(name="Author", value=interaction.user.mention, inline=True)
        embed.set_footer(text="Dravian Daily | Republic of Dravia")
        await interaction.response.send_message(embed=embed)
        audit_log.info("News article #%s published by %s", article_id, interaction.user.id)

    @news_group.command(name="list", description="View published news")
    @app_commands.describe(page="Page number")
    async def news_list(self, interaction: discord.Interaction, page: int = 1):
        if page < 1:
            page = 1
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM news_articles WHERE kind = 'news' ORDER BY id DESC LIMIT 5 OFFSET ?",
                ((page - 1) * 5,),
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title="📰 Dravian Daily — Archives", color=COLOR_ACCENT)
        if not rows:
            embed.description = "No articles published yet."
        else:
            for r in rows:
                embed.add_field(
                    name=f"#{r['id']} {r['title']}",
                    value=f"{(r['content'] or '')[:200]}...\n_{(r['published_at'] or '')[:10]}_",
                    inline=False,
                )
        embed.set_footer(text=f"Page {page}")
        await interaction.response.send_message(embed=embed)

    @news_group.command(name="latest", description="View the latest edition")
    async def news_latest(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM news_articles ORDER BY id DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message("No editions published yet.", ephemeral=True)
            return

        embed = discord.Embed(title=f"📰 {row['title']}", description=(row["content"] or "")[:4000], color=COLOR_GOLD)
        embed.add_field(name="Published", value=(row["published_at"] or "")[:16].replace("T", " "), inline=True)
        embed.set_footer(text="Dravian Daily | Republic of Dravia")
        await interaction.response.send_message(embed=embed)

    @gazette_group.command(name="announce", description="Official government announcement")
    @app_commands.describe(title="Announcement title", content="Announcement body")
    async def gazette_announce(self, interaction: discord.Interaction, title: str, content: str):
        article_id = await self.publish(title, content, str(interaction.user.id), "gazette")
        embed = discord.Embed(
            title=f"🏛️ OFFICIAL GAZETTE — {title}",
            description=content[:4000],
            color=COLOR_CRIMSON,
        )
        embed.add_field(name="Reference", value=f"#{article_id}", inline=True)
        embed.set_footer(text="Government of the Republic of Dravia | By authority")
        await interaction.response.send_message(embed=embed)
        audit_log.info("Gazette announcement #%s by %s", article_id, interaction.user.id)

    @gazette_group.command(name="budget", description="View monthly budget report")
    async def gazette_budget(self, interaction: discord.Interaction):
        stats = await self.db.get_economy_stats()
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE from_user = 'system'"
            ) as cursor:
                outflows = (await cursor.fetchone())[0]
            async with db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE to_user = 'system'"
            ) as cursor:
                inflows = (await cursor.fetchone())[0]
            async with db.execute("SELECT COALESCE(SUM(amount),0) FROM taxes WHERE paid = 1") as cursor:
                revenue = (await cursor.fetchone())[0]

        embed = discord.Embed(title="💰 Monthly Budget Report", color=COLOR_GOLD)
        embed.add_field(name="Money Supply", value=f"🪙 **{stats['total_money'] or 0:,}**", inline=True)
        embed.add_field(name="Tax Revenue (collected)", value=f"🪙 **{revenue:,}**", inline=True)
        embed.add_field(name="Government Outflows", value=f"🪙 **{outflows:,}**", inline=True)
        embed.add_field(name="Government Inflows", value=f"🪙 **{inflows:,}**", inline=True)
        embed.set_footer(text="Republic of Dravia | Ministry of Finance")
        await interaction.response.send_message(embed=embed)

    @gazette_group.command(name="production", description="View weekly production report")
    async def gazette_production(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT COUNT(*) FROM businesses WHERE is_active = 1") as cursor:
                businesses = (await cursor.fetchone())[0]
            async with db.execute("SELECT COALESCE(SUM(daily_points),0) FROM businesses WHERE is_active = 1") as cursor:
                points = (await cursor.fetchone())[0]
            async with db.execute("SELECT COALESCE(SUM(quantity),0) FROM business_inventory") as cursor:
                units = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM mining_concessions WHERE is_active = 1") as cursor:
                mines = (await cursor.fetchone())[0]

        embed = discord.Embed(title="🏭 Weekly Production Report", color=COLOR_ACCENT)
        embed.add_field(name="Active Businesses", value=f"**{businesses}**", inline=True)
        embed.add_field(name="Total Daily Capacity", value=f"**{points} pts**", inline=True)
        embed.add_field(name="Goods in Stock", value=f"**{units:,}**", inline=True)
        embed.add_field(name="Active Mining Concessions", value=f"**{mines}**", inline=True)
        embed.set_footer(text="Republic of Dravia | Deadline: Monday 12:00")
        await interaction.response.send_message(embed=embed)

    @gazette_group.command(name="enforcement", description="View SEC enforcement report")
    async def gazette_enforcement(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT COUNT(*) FROM ia_cases") as cursor:
                ia_cases = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM consumer_complaints WHERE status != 'resolved'") as cursor:
                open_complaints = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM customs_declarations WHERE status = 'seized'") as cursor:
                seizures = (await cursor.fetchone())[0]

        embed = discord.Embed(title="⚖️ Enforcement Report", color=COLOR_CRIMSON)
        embed.add_field(name="IA Cases (Police)", value=f"**{ia_cases}**", inline=True)
        embed.add_field(name="Open Consumer Complaints", value=f"**{open_complaints}**", inline=True)
        embed.add_field(name="Customs Seizures", value=f"**{seizures}**", inline=True)
        embed.set_footer(text="Republic of Dravia | Securities Enforcement Commission")
        await interaction.response.send_message(embed=embed)

    @gazette_group.command(name="economic", description="View economic indicators")
    async def gazette_economic(self, interaction: discord.Interaction):
        stats = await self.db.get_economy_stats()
        users = stats["total_users"] or 0
        money = stats["total_money"] or 0
        avg = stats["avg_balance"] or 0
        gdp = money * 1.5  # multiplier effect tracking

        embed = discord.Embed(title="📊 Economic Indicators", color=COLOR_GOLD)
        embed.add_field(name="Citizens", value=f"**{users:,}**", inline=True)
        embed.add_field(name="Money Supply", value=f"🪙 **{money:,}**", inline=True)
        embed.add_field(name="Average Wealth", value=f"🪙 **{avg:.0f}**", inline=True)
        embed.add_field(name="Estimated GDP (1.5x multiplier)", value=f"🪙 **{gdp:,.0f}**", inline=True)
        embed.add_field(name="Starting Balance", value="🪙 **500**", inline=True)
        embed.set_footer(text="Republic of Dravia | Central Bank")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(News(bot))
