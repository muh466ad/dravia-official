"""Dravia State Bot - Investment Funds (Chrysanthemum Fund Exchange)

Tables: `investment_funds`, `fund_holdings`, `exchange_rates`. Fund Managers
open funds and publish rates; citizens invest Ovi and redeem later. Redemptions
consume holdings oldest-first so the books always balance. Dates render through
`stamp()`.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, now, ovi, success, warning
from utils.checks import requires_fund_manager
from utils.validation import amount as validate_amount
from utils.validation import percentage, text

FUND_TYPES = ["Growth", "Income", "Index"]

_FUND_COLS = ("fund_id", "name", "fund_type", "manager_id",
              "total_assets", "min_investment", "created_at")


class Funds(DraviaCog):
    """Chrysanthemum Fund Exchange commands."""

    group_name = "market"
    fund_group = app_commands.Group(name="fund", description="Investment funds and FX rates")

    # ------------------------------------------------------------ helpers
    async def _get_fund(self, fund_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM investment_funds WHERE fund_id = ?", (fund_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_FUND_COLS, row)) if row else None

    # ------------------------------------------------------------ commands
    @fund_group.command(name="create", description="Open a fund (Fund Manager)")
    @app_commands.describe(name="Fund name", fund_type="Strategy",
                           min_investment="Minimum ticket in Ovi")
    @app_commands.choices(fund_type=[app_commands.Choice(name=t, value=t) for t in FUND_TYPES])
    @handles_validation
    @requires_fund_manager
    async def fund_create(self, interaction: discord.Interaction, name: str,
                          fund_type: str = "Growth", min_investment: int = 1000):
        name = text(name, field="Fund name", maximum=60)
        fund_type = fund_type if fund_type in FUND_TYPES else FUND_TYPES[0]
        min_investment = validate_amount(min_investment, field="Minimum investment",
                                         minimum=1, maximum=1_000_000)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT 1 FROM investment_funds WHERE name = ? COLLATE NOCASE", (name,)
            ) as cur:
                if await cur.fetchone():
                    await self.fail(interaction, f"A fund named **{name}** already exists.")
                    return
            await db.execute(
                "INSERT INTO investment_funds (name, fund_type, manager_id, total_assets, "
                "min_investment, created_at) VALUES (?, ?, ?, 0, ?, date('now'))",
                (name, fund_type, str(interaction.user.id), min_investment),
            )
            await db.commit()
            async with db.execute("SELECT MAX(fund_id) FROM investment_funds") as cur:
                fund_id = (await cur.fetchone())[0]
        log_action("fund", "create", str(interaction.user.id), fund=fund_id, name=name)
        embed = success("Fund listed", f"**{name}** ({fund_type}) is open for subscriptions.")
        embed.add_field(name="Fund ID", value=f"#{fund_id}")
        embed.add_field(name="Minimum ticket", value=ovi(min_investment))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fund_group.command(name="list", description="Every fund on the exchange")
    async def fund_list(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT fund_id, name, fund_type, total_assets, min_investment "
                "FROM investment_funds ORDER BY total_assets DESC LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="📈 Fund Exchange", color=COLOR_GOLD)
        if not rows:
            embed.description = "No funds listed. Fund Managers open one with `/fund create`."
        for fund_id, name, fund_type, assets, minimum in rows:
            embed.add_field(
                name=f"#{fund_id} {name}",
                value=f"{fund_type} · assets {ovi(assets)} · min {ovi(minimum)}",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fund_group.command(name="info", description="Fund details and investor count")
    @app_commands.describe(fund_id="Fund to inspect")
    async def fund_info(self, interaction: discord.Interaction, fund_id: int):
        fund = await self._get_fund(fund_id)
        if fund is None:
            await self.fail(interaction, f"No fund #{fund_id} exists.")
            return
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM fund_holdings WHERE fund_id = ?",
                (fund_id,),
            ) as cur:
                investors, held = await cur.fetchone()
        embed = DraviaEmbed(title=f"📈 {fund['name']}", color=COLOR_GOLD)
        embed.add_field(name="Strategy", value=fund["fund_type"], inline=True)
        embed.add_field(name="Manager", value=f"<@{fund['manager_id']}>", inline=True)
        embed.add_field(name="Listed", value=stamp(fund["created_at"]), inline=True)
        embed.add_field(name="Total assets", value=ovi(fund["total_assets"]), inline=True)
        embed.add_field(name="Subscribed", value=ovi(held), inline=True)
        embed.add_field(name="Investors", value=str(investors), inline=True)
        embed.add_field(name="Minimum ticket", value=ovi(fund["min_investment"]), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fund_group.command(name="invest", description="Subscribe to a fund")
    @app_commands.describe(fund_id="Fund to buy into", ovi_amount="Ovi to invest")
    @handles_validation
    async def fund_invest(self, interaction: discord.Interaction, fund_id: int,
                          ovi_amount: int):
        fund = await self._get_fund(fund_id)
        if fund is None:
            await self.fail(interaction, f"No fund #{fund_id} exists.")
            return
        ovi_amount = validate_amount(ovi_amount, field="Amount", minimum=1,
                                     maximum=100_000_000)
        if ovi_amount < fund["min_investment"]:
            await self.fail(interaction,
                            f"Minimum ticket is {ovi(fund['min_investment'])} "
                            f"(you offered {ovi(ovi_amount)}).")
            return
        user_id = str(interaction.user.id)
        if not await self.debit(user_id, ovi_amount, "fund", f"Subscribe #{fund_id}"):
            await self.fail(interaction, f"You cannot afford {ovi(ovi_amount)}.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO fund_holdings (fund_id, investor_id, amount, invested_at) "
                "VALUES (?, ?, ?, date('now'))",
                (fund_id, user_id, ovi_amount),
            )
            await db.execute(
                "UPDATE investment_funds SET total_assets = total_assets + ? WHERE fund_id = ?",
                (ovi_amount, fund_id),
            )
            await db.commit()
        log_action("fund", "invest", user_id, fund=fund_id, amount=ovi_amount)
        embed = success("Subscription filled",
                        f"{ovi(ovi_amount)} into **{fund['name']}**.")
        embed.add_field(name="Fund assets", value=ovi(fund["total_assets"] + ovi_amount))
        embed.add_field(name="Redeem", value="Use `/fund redeem` to cash back out.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fund_group.command(name="redeem", description="Cash out of a fund")
    @app_commands.describe(fund_id="Fund to sell back", ovi_amount="Ovi to redeem")
    @handles_validation
    async def fund_redeem(self, interaction: discord.Interaction, fund_id: int,
                          ovi_amount: int):
        fund = await self._get_fund(fund_id)
        if fund is None:
            await self.fail(interaction, f"No fund #{fund_id} exists.")
            return
        ovi_amount = validate_amount(ovi_amount, field="Amount", minimum=1,
                                     maximum=100_000_000)
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM fund_holdings "
                "WHERE fund_id = ? AND investor_id = ?",
                (fund_id, user_id),
            ) as cur:
                held = (await cur.fetchone())[0]
            if held < ovi_amount:
                await self.fail(interaction,
                                f"Your stake is {ovi(held)} — you cannot redeem {ovi(ovi_amount)}.")
                return
            # Consume oldest subscriptions first so FIFO investors keep their place.
            remaining = ovi_amount
            async with db.execute(
                "SELECT holding_id, amount FROM fund_holdings "
                "WHERE fund_id = ? AND investor_id = ? ORDER BY holding_id",
                (fund_id, user_id),
            ) as cur:
                lots = await cur.fetchall()
            for holding_id, lot in lots:
                if remaining <= 0:
                    break
                take = min(remaining, lot)
                if take == lot:
                    await db.execute("DELETE FROM fund_holdings WHERE holding_id = ?",
                                     (holding_id,))
                else:
                    await db.execute(
                        "UPDATE fund_holdings SET amount = amount - ? WHERE holding_id = ?",
                        (take, holding_id),
                    )
                remaining -= take
            await db.execute(
                "UPDATE investment_funds SET total_assets = total_assets - ? WHERE fund_id = ?",
                (ovi_amount, fund_id),
            )
            await db.commit()
        await self.credit(user_id, ovi_amount, "fund", f"Redeem #{fund_id}")
        log_action("fund", "redeem", user_id, fund=fund_id, amount=ovi_amount)
        embed = success("Redeemed", f"{ovi(ovi_amount)} returned from **{fund['name']}**.")
        embed.add_field(name="Remaining stake", value=ovi(held - ovi_amount))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fund_group.command(name="portfolio", description="Your holdings across all funds")
    async def fund_portfolio(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT f.fund_id, f.name, SUM(h.amount) FROM fund_holdings h "
                "JOIN investment_funds f ON f.fund_id = h.fund_id "
                "WHERE h.investor_id = ? GROUP BY f.fund_id ORDER BY SUM(h.amount) DESC",
                (user_id,),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title=f"📈 Portfolio — {interaction.user.display_name}",
                            color=COLOR_GOLD)
        if not rows:
            embed.description = "You hold no funds. `/fund invest` opens a position."
        total = 0
        for fund_id, name, stake in rows:
            total += stake
            embed.add_field(name=f"#{fund_id} {name}", value=ovi(stake))
        embed.add_field(name="Total invested", value=ovi(total))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fund_group.command(name="rates", description="Published exchange rates")
    async def fund_rates(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT currency, rate, updated_at FROM exchange_rates "
                "ORDER BY currency LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="💱 Exchange Rates", color=COLOR_GOLD)
        if not rows:
            embed.description = "No rates published. Fund Managers set them with `/fund rate`."
        for currency, rate, updated_at in rows:
            embed.add_field(name=currency,
                            value=f"1 Ovi = {rate:g} {currency} · {stamp(updated_at)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fund_group.command(name="rate", description="Publish an exchange rate (Fund Manager)")
    @app_commands.describe(currency="Currency code (e.g. USD)", rate="Value of 1 Ovi")
    @handles_validation
    @requires_fund_manager
    async def fund_rate(self, interaction: discord.Interaction, currency: str,
                        rate: float):
        currency = text(currency, field="Currency", minimum=3, maximum=8).upper()
        rate = percentage(rate, maximum=1_000_000.0)
        async with await self.db.get_connection() as db:
            cur = await db.execute(
                "UPDATE exchange_rates SET rate = ?, updated_at = ? WHERE currency = ?",
                (rate, now(), currency),
            )
            if cur.rowcount == 0:
                await db.execute(
                    "INSERT INTO exchange_rates (currency, rate, updated_at) VALUES (?, ?, ?)",
                    (currency, rate, now()),
                )
            await db.commit()
        log_action("fund", "rate", str(interaction.user.id), currency=currency, rate=rate)
        embed = success("Rate published", f"1 Ovi = **{rate:g} {currency}**")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Funds(bot))
