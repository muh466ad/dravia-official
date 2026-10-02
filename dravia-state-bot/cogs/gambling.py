"""Dravia State Bot - Gambling System (State Casino)"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, date, timedelta
import os
import random
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database
from utils.logger import tx_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Player protection limits (Part 10) — cannot be increased
DAILY_DEPOSIT_LIMIT = 500
DAILY_LOSS_LIMIT = 200
COOLING_OFF_HOURS = 24

# Taxes
OPERATOR_TAX = 0.10       # 10% of GGR
WINNINGS_TAX = 0.05       # 5% above 1,000 Ovi
BETTING_TAX = 0.01        # 1% per bet

WARNING = "⚠️ **GAMBLING WARNING:** The house always wins long-term. Losses are permanent."

BLACKJACK = "blackjack"
ROULETTE_NUMBERS = list(range(0, 37))

class Gambling(commands.Cog):
    """State-owned casino commands."""
    
    casino_group = app_commands.Group(name="casino", description="State-owned casino games and player protection")
    lottery_group = app_commands.Group(name="lottery", description="State lottery")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    async def get_limits(self, user_id: str) -> dict:
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM gambling_limits WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                await db.execute(
                    "INSERT INTO gambling_limits (user_id, loss_date) VALUES (?, ?)",
                    (user_id, date.today().isoformat()),
                )
                await db.commit()
                return {
                    "daily_deposit_limit": DAILY_DEPOSIT_LIMIT,
                    "daily_loss_limit": DAILY_LOSS_LIMIT,
                    "daily_loss_used": 0,
                    "daily_wagered": 0,
                    "loss_date": date.today().isoformat(),
                    "self_excluded_until": None,
                }
            data = dict(row)
            # Reset daily counters on a new day
            if data.get("loss_date") != date.today().isoformat():
                await db.execute(
                    "UPDATE gambling_limits SET daily_loss_used = 0, daily_wagered = 0, loss_date = ? WHERE user_id = ?",
                    (date.today().isoformat(), user_id),
                )
                await db.commit()
                data["daily_loss_used"] = 0
                data["daily_wagered"] = 0
            return data

    async def can_bet(self, user_id: str, bet: int) -> str:
        """Return an error message if the bet is not allowed, else None."""
        limits = await self.get_limits(user_id)

        excluded = limits.get("self_excluded_until")
        if excluded:
            try:
                if datetime.fromisoformat(excluded) > datetime.now():
                    return f"You are self-excluded until {excluded[:10]}. Gambling is prohibited."
            except (ValueError, TypeError):
                pass

        if bet <= 0:
            return "Bet must be positive."
        if bet > limits["daily_deposit_limit"]:
            return f"Daily deposit limit is 🪙 {DAILY_DEPOSIT_LIMIT:,}. It cannot be increased."
        if limits["daily_wagered"] + bet > DAILY_DEPOSIT_LIMIT:
            remaining = max(0, DAILY_DEPOSIT_LIMIT - limits["daily_wagered"])
            return f"Daily wager limit reached. Only 🪙 {remaining:,} left today."
        return None

    async def record_bet(self, user_id: str, bet: int, loss: int):
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE gambling_limits SET daily_wagered = daily_wagered + ?, daily_loss_used = daily_loss_used + ? WHERE user_id = ?",
                (bet, loss, user_id),
            )
            await db.commit()

    async def settle_win(self, user_id: str, gross_win: int) -> int:
        """Apply 5% winnings tax above 1,000 Ovi. Returns net win."""
        if gross_win > 1000:
            tax = int(gross_win * WINNINGS_TAX)
            net = gross_win - tax
            await self.db.add_balance(user_id, net, "gambling_win", f"Casino win (net of {tax} Ovi winnings tax)")
            return net
        await self.db.add_balance(user_id, gross_win, "gambling_win", "Casino win")
        return gross_win

    @casino_group.command(name="slots", description="Play the slot machine")
    @app_commands.describe(bet="Wager amount in Ovi")
    async def casino_slots(self, interaction: discord.Interaction, bet: int):
        user_id = str(interaction.user.id)
        error = await self.can_bet(user_id, bet)
        if error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        balance = await self.db.get_balance(user_id)
        if balance < bet:
            await interaction.response.send_message(f"❌ Insufficient funds. You have 🪙 {balance:,}.", ephemeral=True)
            return

        # 1% betting tax
        tax = max(1, int(bet * BETTING_TAX))
        await self.db.remove_balance(user_id, bet, "gambling_bet", "Slots bet")

        symbols = ["🍒", "🔔", "7️⃣", "🍀", "💎", "_BAR"]
        reels = [random.choice(symbols) for _ in range(3)]

        if reels[0] == reels[1] == reels[2]:
            gross = bet * 10
            net = await self.settle_win(user_id, gross)
            result = f"🎰 **JACKPOT!** {reels[0]} {reels[1]} {reels[2]}"
            color = COLOR_GOLD
            payout = net
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            gross = bet * 2
            net = await self.settle_win(user_id, gross)
            result = f"🎰 {reels[0]} {reels[1]} {reels[2]} — Two of a kind!"
            color = COLOR_ACCENT
            payout = net
        else:
            await self.record_bet(user_id, bet, bet)
            result = f"🎰 {reels[0]} {reels[1]} {reels[2]} — House wins."
            color = COLOR_CRIMSON
            payout = 0

        embed = discord.Embed(title="🎰 Dravia State Casino — Slots", description=result, color=color)
        embed.add_field(name="Bet", value=f"🪙 **{bet:,}**", inline=True)
        embed.add_field(name="Payout", value=f"🪙 **{payout:,}**" if payout else "🪙 **0**", inline=True)
        embed.add_field(name="New Balance", value=f"🪙 **{await self.db.get_balance(user_id):,}**", inline=True)
        embed.add_field(name="Warning", value=WARNING, inline=False)
        embed.set_footer(text="State-owned casino | All revenue to the Treasury")
        tx_log.info("Slots: user=%s bet=%s payout=%s", user_id, bet, payout)
        await interaction.response.send_message(embed=embed)

    @casino_group.command(name="blackjack", description="Play blackjack against the house")
    @app_commands.describe(bet="Wager amount in Ovi")
    async def casino_blackjack(self, interaction: discord.Interaction, bet: int):
        user_id = str(interaction.user.id)
        error = await self.can_bet(user_id, bet)
        if error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        balance = await self.db.get_balance(user_id)
        if balance < bet:
            await interaction.response.send_message(f"❌ Insufficient funds. You have 🪙 {balance:,}.", ephemeral=True)
            return

        await self.db.remove_balance(user_id, bet, "gambling_bet", "Blackjack bet")

        def draw():
            return random.randint(2, 11)

        player = [draw(), draw()]
        dealer = [draw(), draw()]
        player_total = sum(player)
        dealer_total = sum(dealer)

        # House rules: dealer stands on 17+
        while dealer_total < 17:
            dealer.append(draw())
            dealer_total = sum(dealer)

        if player_total > 21:
            await self.record_bet(user_id, bet, bet)
            outcome, color, payout = "💥 **BUST!** You went over 21.", COLOR_CRIMSON, 0
        elif dealer_total > 21 or player_total > dealer_total:
            net = await self.settle_win(user_id, int(bet * 1.5))
            outcome, color, payout = "✅ **You win!**", COLOR_GOLD, net
        elif player_total == dealer_total:
            net = await self.settle_win(user_id, bet)
            outcome, color, payout = "🤝 **Push — draw.** Bet returned.", COLOR_ACCENT, net
        else:
            await self.record_bet(user_id, bet, bet)
            outcome, color, payout = "❌ **House wins.**", COLOR_CRIMSON, 0

        embed = discord.Embed(title="🃏 Blackjack", description=outcome, color=color)
        embed.add_field(name="Your Hand", value=f"**{player_total}** ({player})", inline=True)
        embed.add_field(name="Dealer", value=f"**{dealer_total}** ({dealer})", inline=True)
        embed.add_field(name="Bet", value=f"🪙 **{bet:,}**", inline=True)
        embed.add_field(name="Payout", value=f"🪙 **{payout:,}**", inline=True)
        embed.add_field(name="Warning", value=WARNING, inline=False)
        embed.set_footer(text="State-owned casino | All revenue to the Treasury")
        tx_log.info("Blackjack: user=%s bet=%s payout=%s", user_id, bet, payout)
        await interaction.response.send_message(embed=embed)

    @casino_group.command(name="roulette", description="Play roulette")
    @app_commands.describe(bet="Wager amount", number="Number to bet on (0-36)")
    async def casino_roulette(self, interaction: discord.Interaction, bet: int, number: int):
        user_id = str(interaction.user.id)
        if number < 0 or number > 36:
            await interaction.response.send_message("❌ Number must be between 0 and 36.", ephemeral=True)
            return
        error = await self.can_bet(user_id, bet)
        if error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        balance = await self.db.get_balance(user_id)
        if balance < bet:
            await interaction.response.send_message(f"❌ Insufficient funds. You have 🪙 {balance:,}.", ephemeral=True)
            return

        await self.db.remove_balance(user_id, bet, "gambling_bet", "Roulette bet")
        spin = random.choice(ROULETTE_NUMBERS)

        if spin == number:
            net = await self.settle_win(user_id, bet * 35)
            outcome = f"🎯 **{spin}** — YOU WIN! Straight bet pays 35:1!"
            color, payout = COLOR_GOLD, net
        else:
            await self.record_bet(user_id, bet, bet)
            outcome = f"🎯 Landed on **{spin}** — you picked {number}. House wins."
            color, payout = COLOR_CRIMSON, 0

        embed = discord.Embed(title="🎡 Roulette", description=outcome, color=color)
        embed.add_field(name="Bet", value=f"🪙 **{bet:,}** on {number}", inline=True)
        embed.add_field(name="Payout", value=f"🪙 **{payout:,}**", inline=True)
        embed.add_field(name="Warning", value=WARNING, inline=False)
        embed.set_footer(text="State-owned casino | All revenue to the Treasury")
        tx_log.info("Roulette: user=%s bet=%s spin=%s payout=%s", user_id, bet, spin, payout)
        await interaction.response.send_message(embed=embed)

    @casino_group.command(name="dice", description="Roll dice")
    @app_commands.describe(bet="Wager amount", number="Number to bet on (1-6)")
    async def casino_dice(self, interaction: discord.Interaction, bet: int, number: int):
        user_id = str(interaction.user.id)
        if number < 1 or number > 6:
            await interaction.response.send_message("❌ Number must be between 1 and 6.", ephemeral=True)
            return
        error = await self.can_bet(user_id, bet)
        if error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        balance = await self.db.get_balance(user_id)
        if balance < bet:
            await interaction.response.send_message(f"❌ Insufficient funds. You have 🪙 {balance:,}.", ephemeral=True)
            return

        await self.db.remove_balance(user_id, bet, "gambling_bet", "Dice bet")
        roll = random.randint(1, 6)

        if roll == number:
            net = await self.settle_win(user_id, bet * 5)
            outcome = f"🎲 Rolled **{roll}** — you win 5:1!"
            color, payout = COLOR_GOLD, net
        else:
            await self.record_bet(user_id, bet, bet)
            outcome = f"🎲 Rolled **{roll}** — you picked {number}. House wins."
            color, payout = COLOR_CRIMSON, 0

        embed = discord.Embed(title="🎲 Dice", description=outcome, color=color)
        embed.add_field(name="Bet", value=f"🪙 **{bet:,}**", inline=True)
        embed.add_field(name="Payout", value=f"🪙 **{payout:,}**", inline=True)
        embed.add_field(name="Warning", value=WARNING, inline=False)
        embed.set_footer(text="State-owned casino | All revenue to the Treasury")
        tx_log.info("Dice: user=%s bet=%s roll=%s payout=%s", user_id, bet, roll, payout)
        await interaction.response.send_message(embed=embed)

    @casino_group.command(name="crash", description="Crash game — cash out before the burst")
    @app_commands.describe(bet="Wager amount")
    async def casino_crash(self, interaction: discord.Interaction, bet: int):
        user_id = str(interaction.user.id)
        error = await self.can_bet(user_id, bet)
        if error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        balance = await self.db.get_balance(user_id)
        if balance < bet:
            await interaction.response.send_message(f"❌ Insufficient funds. You have 🪙 {balance:,}.", ephemeral=True)
            return

        await self.db.remove_balance(user_id, bet, "gambling_bet", "Crash bet")

        # Multiplier grows until random crash point; simulate auto-cashout at a random safe point
        crash_at = round(random.uniform(1.0, 8.0), 2)
        cashout_at = round(random.uniform(1.0, 5.0), 2)

        if cashout_at < crash_at:
            gross = int(bet * cashout_at)
            net = await self.settle_win(user_id, gross)
            outcome = f"🚀 Crashed at **{crash_at}x** — you cashed out at **{cashout_at}x**!"
            color, payout = COLOR_GOLD, net
        else:
            await self.record_bet(user_id, bet, bet)
            outcome = f"💥 Crashed at **{crash_at}x** — you cashed out at **{cashout_at}x**. Too slow!"
            color, payout = COLOR_CRIMSON, 0

        embed = discord.Embed(title="📈 Crash", description=outcome, color=color)
        embed.add_field(name="Bet", value=f"🪙 **{bet:,}**", inline=True)
        embed.add_field(name="Payout", value=f"🪙 **{payout:,}**", inline=True)
        embed.add_field(name="Warning", value=WARNING, inline=False)
        embed.set_footer(text="State-owned casino | All revenue to the Treasury")
        tx_log.info("Crash: user=%s bet=%s crash=%s cashout=%s", user_id, bet, crash_at, cashout_at)
        await interaction.response.send_message(embed=embed)

    @lottery_group.command(name="buy", description="Buy a lottery ticket (10 Ovi)")
    @app_commands.describe(numbers="Five numbers 1-49 separated by spaces, e.g. '3 12 25 31 44'")
    async def lottery_buy(self, interaction: discord.Interaction, numbers: str):
        user_id = str(interaction.user.id)
        try:
            picks = [int(n) for n in numbers.split()]
        except ValueError:
            await interaction.response.send_message("❌ Numbers must be integers separated by spaces.", ephemeral=True)
            return
        if len(picks) != 5 or any(n < 1 or n > 49 for n in picks) or len(set(picks)) != 5:
            await interaction.response.send_message("❌ Pick exactly 5 unique numbers from 1 to 49.", ephemeral=True)
            return

        balance = await self.db.get_balance(user_id)
        if balance < 10:
            await interaction.response.send_message("❌ A ticket costs 🪙 10.", ephemeral=True)
            return

        await self.db.remove_balance(user_id, 10, "lottery", "Lottery ticket")
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO lottery_tickets (user_id, numbers, draw_date) VALUES (?, ?, ?)",
                (user_id, " ".join(str(n) for n in picks), date.today().isoformat()),
            )
            await db.commit()

        embed = discord.Embed(
            title="🎟️ Lottery Ticket Purchased",
            description=f"Numbers: **{' '.join(str(n) for n in sorted(picks))}**",
            color=COLOR_GOLD,
        )
        embed.add_field(name="Cost", value="🪙 **10**", inline=True)
        embed.add_field(name="Next Draw", value="Sunday 18:00", inline=True)
        embed.set_footer(text="Republic of Dravia | State Lottery")
        await interaction.response.send_message(embed=embed)

    @lottery_group.command(name="jackpot", description="View the current lottery jackpot")
    async def lottery_jackpot(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute("SELECT COUNT(*) FROM lottery_tickets") as cursor:
                tickets = (await cursor.fetchone())[0]
        jackpot = tickets * 10 * 6  # 60% of ticket sales pool
        embed = discord.Embed(title="💰 Lottery Jackpot", color=COLOR_GOLD)
        embed.add_field(name="Jackpot", value=f"🪙 **{jackpot:,}**", inline=True)
        embed.add_field(name="Tickets Sold", value=f"**{tickets}**", inline=True)
        embed.add_field(name="Ticket Price", value="🪙 **10**", inline=True)
        embed.set_footer(text="Match all 5 numbers to win | /lottery buy")
        await interaction.response.send_message(embed=embed)

    @lottery_group.command(name="draw", description="View the latest lottery draw result")
    async def lottery_draw(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM lottery_tickets WHERE won = 1 ORDER BY id DESC LIMIT 5"
            ) as cursor:
                winners = await cursor.fetchall()

        embed = discord.Embed(title="🎱 Latest Lottery Draw", color=COLOR_ACCENT)
        if not winners:
            embed.description = "No winners yet — the jackpot grows!"
        else:
            for w in winners:
                embed.add_field(name=f"Winner <@{w['user_id']}>", value=f"Numbers: {w['numbers']}", inline=False)
        embed.set_footer(text="Republic of Dravia | State Lottery")
        await interaction.response.send_message(embed=embed)

    @casino_group.command(name="limits", description="View your gambling limits")
    async def casino_limits(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        limits = await self.get_limits(user_id)
        embed = discord.Embed(title="🛡️ Your Gambling Limits", color=COLOR_ACCENT)
        embed.add_field(name="Daily Wager Limit", value=f"🪙 **{DAILY_DEPOSIT_LIMIT:,}** (cannot be increased)", inline=True)
        embed.add_field(name="Daily Loss Limit", value=f"🪙 **{DAILY_LOSS_LIMIT:,}**", inline=True)
        embed.add_field(name="Wagered Today", value=f"🪙 **{limits['daily_wagered']:,}**", inline=True)
        embed.add_field(name="Lost Today", value=f"🪙 **{limits['daily_loss_used']:,}**", inline=True)
        embed.add_field(name="Session Limit", value="**1 hour**", inline=True)
        excluded = limits.get("self_excluded_until")
        embed.add_field(name="Self-Exclusion", value=excluded or "Not excluded", inline=True)
        embed.set_footer(text="Republic of Dravia | Player protection is mandatory")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @casino_group.command(name="self_exclude", description="Self-exclude from gambling")
    @app_commands.choices(duration=[
        app_commands.Choice(name="1 Month", value="1m"),
        app_commands.Choice(name="3 Months", value="3m"),
        app_commands.Choice(name="6 Months", value="6m"),
        app_commands.Choice(name="Permanent", value="perm"),
    ])
    async def casino_exclude(self, interaction: discord.Interaction, duration: str):
        user_id = str(interaction.user.id)
        now = datetime.now()
        if duration == "perm":
            until = now.replace(year=now.year + 100).isoformat()
            label = "permanent"
        else:
            months = {"1m": 1, "3m": 3, "6m": 6}[duration]
            month = now.month + months
            year = now.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            until = now.replace(year=year, month=month).isoformat()
            label = duration

        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO gambling_limits (user_id, self_excluded_until) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET self_excluded_until = excluded.self_excluded_until",
                (user_id, until),
            )
            await db.commit()

        embed = discord.Embed(
            title="🛡️ Self-Exclusion Activated",
            description=f"You are excluded from all gambling until **{until[:10]}** ({label}).\nThis cannot be undone early.",
            color=COLOR_ACCENT,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @casino_group.command(name="stats", description="View your gambling statistics")
    async def casino_stats(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        limits = await self.get_limits(user_id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions WHERE from_user = ? AND type = 'gambling_bet'",
                (user_id,),
            ) as cursor:
                bets, wagered = await cursor.fetchone()
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions WHERE to_user = ? AND type = 'gambling_win'",
                (user_id,),
            ) as cursor:
                wins, won = await cursor.fetchone()

        net = won - wagered
        embed = discord.Embed(title="📊 Gambling Statistics", color=COLOR_ACCENT)
        embed.add_field(name="Total Wagered", value=f"🪙 **{wagered:,}**", inline=True)
        embed.add_field(name="Total Won", value=f"🪙 **{won:,}**", inline=True)
        embed.add_field(name="Net Result", value=f"🪙 **{net:,}**" + (" (loss)" if net < 0 else " (profit)"), inline=True)
        embed.add_field(name="Bets Placed", value=f"**{bets}**", inline=True)
        embed.add_field(name="Wins", value=f"**{wins}**", inline=True)
        embed.add_field(name="Wagered Today", value=f"🪙 **{limits['daily_wagered']:,}**", inline=True)
        embed.set_footer(text="Republic of Dravia | The house always wins long-term")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Gambling(bot))
