"""Dravia State Bot - Achievements (E3)

Milestone rewards. Achievements are seeded on first use so `/achievements list`
is never empty, progress is tracked per citizen, and rewards are claimed exactly
once (the `claimed` column guards against double payment).
"""
import discord
from discord import app_commands
from discord.ext import commands

from config import COLOR_GOLD
from utils.cog import DraviaCog, handles_validation, ovi
from utils.embeds import DraviaEmbed, success, warning
from utils.logger import audit_log
from utils.validation import choice, text

# (name, description, reward, requirement)
ACHIEVEMENTS = [
    ("First 1,000 Ovi", "Hold 1,000 Ovi at once", 100, "balance>=1000"),
    ("First 10,000 Ovi", "Hold 10,000 Ovi at once", 500, "balance>=10000"),
    ("Piggy Bank", "Save 1,000 Ovi in the bank", 250, "savings>=1000"),
    ("Entrepreneur", "Register your first business", 500, "business"),
    ("Homeowner", "Take ownership of a house", 500, "property"),
    ("Millionaire", "Hold 1,000,000 Ovi at once", 10000, "balance>=1000000"),
    ("Citizen of the Year", "First arrest made", 200, "police"),
    ("Tycoon", "Complete your first IPO", 1000, "business"),
]

GROUP = app_commands.Group(name="achievements", description="Milestones and rewards")


class Achievements(DraviaCog):
    group_name = "economy"
    achievements = GROUP

    async def _seed(self):
        async with await self.db.get_connection() as db:
            for name, desc, reward, req in ACHIEVEMENTS:
                await db.execute(
                    "INSERT OR IGNORE INTO achievements (name, description, reward, requirement) "
                    "VALUES (?, ?, ?, ?)", (name, desc, reward, req))
            await db.commit()

    async def evaluate(self, user_id: str):
        """Award any achievement whose requirement the citizen now meets.

        Returns the names newly unlocked, so a caller can celebrate them.
        """
        await self._seed()
        user_id = str(user_id)
        unlocked = []
        balance = await self.balance_of(user_id)

        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(savings),0) FROM bank_accounts WHERE user_id = ?",
                (user_id,)) as cur:
                savings = (await cur.fetchone())[0] or 0
            for table, label in (("businesses", "business"), ("properties", "property"),
                                 ("criminals", "police")):
                async with db.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE "
                        + ("owner_id = ?" if table != "criminals" else "discord_id = ?"),
                        (user_id,)) as cur:
                    count = (await cur.fetchone())[0]
                if count:
                    unlocked.append(label)

            for name, desc, reward, req in ACHIEVEMENTS:
                met = False
                if req.startswith("balance>="):
                    met = balance >= int(req.split(">=")[1])
                elif req.startswith("savings>="):
                    met = savings >= int(req.split(">=")[1])
                elif req in ("business", "property", "police"):
                    met = any(u.startswith(f"{req}:") for u in unlocked)
                if not met:
                    continue
                async with db.execute(
                    "SELECT achievement_id, name FROM achievements WHERE name = ?", (name,)
                ) as cur:
                    row = await cur.fetchone()
                if not row:
                    continue
                # Look the unlock up before inserting: INSERT OR IGNORE only
                # protects against duplicates where the schema carries the
                # UNIQUE (user_id, achievement_id) clause, and either way a
                # second evaluate() must report nothing.
                async with db.execute(
                    "SELECT 1 FROM player_achievements "
                    "WHERE user_id = ? AND achievement_id = ?",
                    (user_id, row[0])) as cur:
                    owned = await cur.fetchone()
                if owned:
                    continue
                await db.execute(
                    "INSERT OR IGNORE INTO player_achievements "
                    "(user_id, achievement_id, achieved_at, claimed) VALUES (?, ?, date('now'), 0)",
                    (user_id, row[0]))
                unlocked.append(f"new:{row[1]}")
            await db.commit()
        return [u[4:] for u in unlocked if u.startswith("new:")]

    @GROUP.command(name="list", description="Every achievement and its reward")
    async def achievements_list(self, interaction: discord.Interaction):
        await self._seed()
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT name, description, reward FROM achievements ORDER BY reward"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🏅 Dravian Achievements", color=COLOR_GOLD)
        for name, desc, reward in rows:
            embed.add_field(name=f"{name} — {ovi(reward)}", value=desc)
        embed.set_footer(text=f"{len(rows)} achievements | Republic of Dravia")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @GROUP.command(name="mine", description="Your unlocked achievements")
    async def achievements_mine(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT a.name, a.reward, p.achieved_at, p.claimed "
                "FROM player_achievements p JOIN achievements a "
                "ON a.achievement_id = p.achievement_id "
                "WHERE p.user_id = ? ORDER BY p.achieved_at DESC", (user_id,)
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message(
                embed=warning("No achievements yet",
                              "Grow your balance, run a business or take a house to unlock your first."),
                ephemeral=True)
            return
        embed = DraviaEmbed(title="🏅 Your Achievements", color=COLOR_GOLD)
        for name, reward, achieved, claimed in rows:
            mark = "✅ claimed" if claimed else "🎁 unclaimed"
            embed.add_field(name=f"{name} {mark}", value=f"Reward {ovi(reward)} · {achieved}")
        embed.set_footer(text="Republic of Dravia | Claim with /achievements claim")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @GROUP.command(name="claim", description="Claim an achievement reward")
    @app_commands.describe(achievement="Name of the achievement")
    @handles_validation
    async def achievements_claim(self, interaction: discord.Interaction,
                                 achievement: str):
        await self._seed()
        name = text(achievement, field="Achievement", maximum=60)
        user_id = str(interaction.user.id)

        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT p.record_id, a.name, a.reward, p.claimed "
                "FROM player_achievements p JOIN achievements a "
                "ON a.achievement_id = p.achievement_id "
                "WHERE p.user_id = ? AND a.name = ?", (user_id, name)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                await self.fail(interaction, f"You have not unlocked **{name}** yet.")
                return
            record_id, real_name, reward, claimed = row
            if claimed:
                await self.fail(interaction, f"**{real_name}** has already been claimed.")
                return
            # Guard the payout with the claimed flag in the same transaction so a
            # double-submit cannot pay twice.
            async with db.execute(
                "UPDATE player_achievements SET claimed = 1 WHERE record_id = ? AND claimed = 0",
                (record_id,)) as cur:
                changed = cur.rowcount
            if changed != 1:
                await interaction.response.send_message(
                    embed=warning("Already claimed", f"**{real_name}** has already been paid."),
                    ephemeral=True)
                return
            await db.commit()

        await self.credit(user_id, reward, "achievement", f"Achievement: {real_name}")
        audit_log.info("achievement %s claimed by %s amount=%s", real_name, user_id, reward)
        embed = success("Achievement claimed", f"**{real_name}** — reward {ovi(reward)}")
        embed.add_field(name="New Balance", value=ovi(await self.balance_of(user_id)))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @GROUP.command(name="progress", description="Progress toward your next achievement")
    async def achievements_progress(self, interaction: discord.Interaction):
        await self._seed()  # a citizen may run /progress before /list or /claim
        user_id = str(interaction.user.id)
        balance = await self.balance_of(user_id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT a.name, a.reward FROM achievements a "
                "LEFT JOIN player_achievements p "
                "  ON p.achievement_id = a.achievement_id AND p.user_id = ? "
                "WHERE p.record_id IS NULL", (user_id,)
            ) as cur:
                remaining = await cur.fetchall()
        if not remaining:
            await interaction.response.send_message(
                embed=success("All unlocked", "You have earned every achievement."), ephemeral=True)
            return
        embed = DraviaEmbed(title="🎯 Still To Unlock", color=COLOR_GOLD)
        embed.add_field(name="Your Balance", value=ovi(balance))
        for name, reward in remaining[:15]:
            embed.add_field(name=f"{name} {ovi(reward)}", value="Not yet unlocked")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Achievements(bot))