"""Dravia State Bot - Scheduled Tasks (APScheduler)

Daily   : 00:00 limit resets, 09:00 morning news, 18:00 evening news
Weekly  : Sun 00:00 salaries, Sun 09:00 UBI, Sun 12:00 taxes, Sun 18:00 production report
Monthly : 1st renewals + budget report, 15th wealth tax assessment
"""
import os
from datetime import datetime, date, timedelta

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import Database
from utils.logger import bot_log, tx_log, error_log, audit_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Grade salaries (civil service)
GRADE_SALARIES = {"A": 3500, "B": 2800, "C": 2200, "D": 1800, "E": 1400, "F": 1000, "G": 700}

# Police rank salaries
POLICE_SALARIES = {
    "General Commissioner": 2800, "Chief of Police": 2500, "Deputy Chief": 2200,
    "Assistant Chief": 1900, "Commander": 1700, "Captain": 1500, "Lieutenant": 1300,
    "Sergeant": 1150, "Corporal": 1000, "Senior Patrol Officer": 900,
    "Patrol Officer III": 800, "Patrol Officer II": 700, "Patrol Officer I": 600,
    "Cadet": 400, "Recruit": 400, "Officer": 700, "Senior Officer": 900,
    "Inspector": 1300, "Chief Inspector": 1700, "Superintendent": 2200, "Commissioner": 2800,
}


class DraviaScheduler:
    """Owns the APScheduler instance and all recurring national tasks."""

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self):
        """Register all jobs and start the scheduler."""
        s = self.scheduler

        # DAILY
        s.add_job(self.reset_daily_limits, CronTrigger(hour=0, minute=0), id="daily_reset", replace_existing=True)
        s.add_job(self.morning_news, CronTrigger(hour=9, minute=0), id="morning_news", replace_existing=True)
        s.add_job(self.evening_news, CronTrigger(hour=18, minute=0), id="evening_news", replace_existing=True)

        # WEEKLY (Sunday)
        s.add_job(self.pay_salaries, CronTrigger(day_of_week="sun", hour=0, minute=0), id="salaries", replace_existing=True)
        s.add_job(self.pay_weekly_ubi, CronTrigger(day_of_week="sun", hour=9, minute=0), id="weekly_ubi", replace_existing=True)
        s.add_job(self.process_taxes, CronTrigger(day_of_week="sun", hour=12, minute=0), id="taxes", replace_existing=True)
        s.add_job(self.production_report, CronTrigger(day_of_week="sun", hour=18, minute=0), id="production", replace_existing=True)

        # MONTHLY
        s.add_job(self.monthly_renewals, CronTrigger(day=1, hour=0, minute=30), id="renewals", replace_existing=True)
        s.add_job(self.monthly_budget, CronTrigger(day=1, hour=9, minute=0), id="budget", replace_existing=True)
        s.add_job(self.wealth_tax, CronTrigger(day=15, hour=9, minute=0), id="wealth_tax", replace_existing=True)

        # QUARTERLY
        s.add_job(self.quarterly_report, CronTrigger(month="1,4,7,10", day=1, hour=12, minute=0),
                  id="quarterly", replace_existing=True)

        s.start()
        bot_log.info("Scheduler started with %s jobs", len(s.get_jobs()))

    def shutdown(self):
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass

    # ---------- helpers ----------

    async def _broadcast(self, title: str, description: str, color: int = 0xD4AF37):
        """Post an announcement to every guild's system channel."""
        for guild in self.bot.guilds:
            channel = guild.system_channel or next(
                (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None
            )
            if channel:
                try:
                    import discord
                    embed = discord.Embed(title=title, description=description, color=color)
                    embed.set_footer(text="Republic of Dravia | Automated")
                    await channel.send(embed=embed)
                except Exception as exc:
                    error_log.warning("Broadcast failed in %s: %s", guild.id, exc)

    # ---------- DAILY ----------

    async def reset_daily_limits(self):
        try:
            async with await self.db.get_connection() as db:
                await db.execute(
                    "UPDATE gambling_limits SET daily_loss_used = 0, daily_wagered = 0, loss_date = ?",
                    (date.today().isoformat(),),
                )
                await db.commit()
            bot_log.info("Daily gambling limits reset")
        except Exception as exc:
            error_log.error("reset_daily_limits: %s", exc, exc_info=True)

    async def morning_news(self):
        await self._broadcast("🌅 Good Morning, Dravia", "The morning news summary is out. Check `/news latest`.", 0xD4AF37)

    async def evening_news(self):
        await self._broadcast("🌆 Evening News Summary", "Day's end in the Republic. Check `/news latest`.", 0x8B0000)

    # ---------- WEEKLY ----------

    async def pay_salaries(self):
        """Sunday 00:00 — pay civil service and police salaries."""
        paid = 0
        try:
            async with await self.db.get_connection() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT user_id, grade FROM civil_servants WHERE status != 'dismissed'") as cursor:
                    for row in await cursor.fetchall():
                        salary = GRADE_SALARIES.get(row["grade"], 700)
                        await self.db.add_balance(row["user_id"], salary, "salary", "Weekly civil service salary")
                        paid += 1
                async with db.execute("SELECT user_id, rank FROM police WHERE status = 'active'") as cursor:
                    for row in await cursor.fetchall():
                        salary = POLICE_SALARIES.get(row["rank"], 600)
                        await self.db.add_balance(row["user_id"], salary, "salary", "Weekly police salary")
                        paid += 1
                # Business employees
                async with db.execute("SELECT user_id, salary FROM business_employees") as cursor:
                    for row in await cursor.fetchall():
                        if row["salary"]:
                            await self.db.add_balance(row["user_id"], row["salary"], "salary", "Business wages")
                            paid += 1
            tx_log.info("Weekly salaries paid: %s recipients", paid)
        except Exception as exc:
            error_log.error("pay_salaries: %s", exc, exc_info=True)

    async def pay_weekly_ubi(self):
        """Sunday 09:00 — 350 Ovi to all active citizens."""
        paid = 0
        try:
            async with await self.db.get_connection() as db:
                async with db.execute("SELECT discord_id FROM citizens WHERE is_active = 1") as cursor:
                    citizens = await cursor.fetchall()
            for (uid,) in citizens:
                await self.db.create_user(uid)
                await self.db.add_balance(uid, 350, "weekly_ubi", "Automatic weekly UBI")
                paid += 1
            tx_log.info("Weekly UBI paid to %s citizens", paid)
        except Exception as exc:
            error_log.error("pay_weekly_ubi: %s", exc, exc_info=True)

    async def process_taxes(self):
        """Sunday 12:00 — deduct outstanding taxes."""
        collected = 0
        try:
            async with await self.db.get_connection() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT user_id, SUM(amount) as owed FROM taxes WHERE paid = 0 AND tax_type != 'audit' GROUP BY user_id"
                ) as cursor:
                    rows = await cursor.fetchall()
                for row in rows:
                    uid, owed = row["user_id"], row["owed"]
                    balance = await self.db.get_balance(uid)
                    if balance >= owed and owed > 0:
                        await self.db.remove_balance(uid, owed, "tax_payment", "Automatic weekly tax deduction")
                        await db.execute("UPDATE taxes SET paid = 1 WHERE user_id = ? AND paid = 0", (uid,))
                        await db.execute("UPDATE users SET tax_paid = tax_paid + ? WHERE user_id = ?", (owed, uid))
                        collected += owed
                await db.commit()
            tx_log.info("Weekly tax collection: %s Ovi", collected)
        except Exception as exc:
            error_log.error("process_taxes: %s", exc, exc_info=True)

    async def production_report(self):
        await self._broadcast("🏭 Weekly Production Report", "Use `/gazette production` for this week's figures.", 0x4FC3F7)

    # ---------- MONTHLY ----------

    async def monthly_renewals(self):
        """1st of the month — business renewals and house rents due; close/repossess defaults."""
        closed, repossessed = 0, 0
        try:
            async with await self.db.get_connection() as db:
                today = date.today().isoformat()
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT id, name FROM businesses WHERE is_active = 1 AND monthly_renewal_due < ?", (today,)
                ) as cursor:
                    for row in await cursor.fetchall():
                        await db.execute("UPDATE businesses SET is_active = 0 WHERE id = ?", (row["id"],))
                        closed += 1
                async with db.execute(
                    "SELECT id, owner_id, house_name FROM houses WHERE is_active = 1 AND rental_due < ?", (today,)
                ) as cursor:
                    for row in await cursor.fetchall():
                        await db.execute("UPDATE houses SET is_active = 0 WHERE id = ?", (row["id"],))
                        repossessed += 1
                await db.commit()
            audit_log.info("Monthly renewals: %s businesses closed, %s houses repossessed", closed, repossessed)
            if closed or repossessed:
                await self._broadcast(
                    "🏢 Monthly Reckoning",
                    f"{closed} business licence(s) expired and {repossessed} house(s) repossessed for non-payment.",
                    0x8B0000,
                )
        except Exception as exc:
            error_log.error("monthly_renewals: %s", exc, exc_info=True)

    async def monthly_budget(self):
        try:
            stats = await self.db.get_economy_stats()
            await self._broadcast(
                "💰 Monthly Budget Report",
                f"Money supply: 🪙 {stats['total_money'] or 0:,} | Citizens: {stats['total_users']}\n"
                "Full figures: `/gazette budget`",
                0xD4AF37,
            )
        except Exception as exc:
            error_log.error("monthly_budget: %s", exc, exc_info=True)

    async def wealth_tax(self):
        """15th — assess annual wealth tax for balances above 50,000 Ovi."""
        assessed = 0
        try:
            from cogs.taxes import wealth_tax as _wealth_tax
            async with await self.db.get_connection() as db:
                async with db.execute("SELECT user_id, balance FROM users WHERE balance >= 50000") as cursor:
                    rows = await cursor.fetchall()
                for uid, balance in rows:
                    owed = _wealth_tax(balance)
                    if owed > 0:
                        await db.execute(
                            "INSERT INTO taxes (user_id, tax_type, amount, week_start, paid, created_at) VALUES (?, 'wealth', ?, ?, 0, ?)",
                            (uid, owed, date.today().isoformat(), datetime.now().isoformat()),
                        )
                        assessed += 1
                await db.commit()
            audit_log.info("Wealth tax assessed for %s citizens", assessed)
        except Exception as exc:
            error_log.error("wealth_tax: %s", exc, exc_info=True)

    # ---------- QUARTERLY ----------

    async def quarterly_report(self):
        try:
            stats = await self.db.get_economy_stats()
            await self._broadcast(
                "📊 Quarterly Economic Report",
                f"Money supply: 🪙 {stats['total_money'] or 0:,} | Citizens: {stats['total_users']} | "
                "Laws reviewed for loopholes. Details: `/gazette economic`",
                0xD4AF37,
            )
            audit_log.info("Quarterly report published")
        except Exception as exc:
            error_log.error("quarterly_report: %s", exc, exc_info=True)
