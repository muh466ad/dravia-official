"""Dravia State Bot - Real Estate (Land Registry)

Records live in `properties`. Citizens buy, improve, gift and sell property;
the registry keeps assessed value so the Revenue Office can tax wealth fairly.
Dates render through `stamp()`.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, ovi, success, warning
from utils.validation import text

#: property_type -> purchase price (also the initial assessed value).
TYPES = {
    "Apartment": 15000,
    "House": 40000,
    "Shop": 60000,
    "Warehouse": 80000,
}

UPGRADE_COST = 5000
UPGRADE_VALUE = 7500   # assessed value gained per upgrade
SELL_RATIO = 0.9       # the state buys back at 90%

_PROPERTY_COLS = ("property_id", "owner_id", "property_type", "location",
                  "value", "status", "built_at")


class Property(DraviaCog):
    """Land Registry commands."""

    group_name = "business"
    property_group = app_commands.Group(name="property", description="Real estate registry")

    # ------------------------------------------------------------ helpers
    async def _get_property(self, property_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM properties WHERE property_id = ?", (property_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_PROPERTY_COLS, row)) if row else None

    def _must_own(self, interaction, prop) -> bool:
        if prop["owner_id"] == str(interaction.user.id):
            return True
        return False

    # ------------------------------------------------------------ commands
    @property_group.command(name="buy", description="Buy property from the state")
    @app_commands.describe(property_type="What to buy", location="Address")
    @app_commands.choices(property_type=[app_commands.Choice(
        name=f"{k} ({v:,} Ovi)", value=k) for k, v in TYPES.items()])
    @handles_validation
    async def property_buy(self, interaction: discord.Interaction, property_type: str,
                           location: str):
        if property_type not in TYPES:
            await self.fail(interaction, f"Unknown property type **{property_type}**.")
            return
        location = text(location, field="Location", maximum=80)
        price = TYPES[property_type]
        user_id = str(interaction.user.id)
        if not await self.debit(user_id, price, "property", f"Bought {property_type}"):
            await self.fail(interaction,
                            f"A **{property_type}** costs {ovi(price)} — you cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO properties (owner_id, property_type, location, value, status, built_at) "
                "VALUES (?, ?, ?, ?, 'owned', date('now'))",
                (user_id, property_type, location, price),
            )
            await db.commit()
            async with db.execute("SELECT MAX(property_id) FROM properties") as cur:
                property_id = (await cur.fetchone())[0]
        log_action("property", "buy", user_id, property=property_id, kind=property_type)
        embed = success("Deed issued", f"**{property_type}** at {location} is yours.")
        embed.add_field(name="Property ID", value=f"#{property_id}")
        embed.add_field(name="Price paid", value=ovi(price))
        embed.add_field(name="Assessed value", value=ovi(price))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @property_group.command(name="sell", description="Sell property back to the state (90% of value)")
    @app_commands.describe(property_id="Property to sell")
    async def property_sell(self, interaction: discord.Interaction, property_id: int):
        prop = await self._get_property(property_id)
        if prop is None:
            await self.fail(interaction, f"No property #{property_id} exists.")
            return
        if prop["status"] != "owned":
            await self.fail(interaction, f"Property #{property_id} is **{prop['status']}**.")
            return
        if not self._must_own(interaction, prop):
            await self.fail(interaction, "That property is not yours to sell.")
            return
        payout = int(prop["value"] * SELL_RATIO)
        async with await self.db.get_connection() as db:
            cur = await db.execute(
                "UPDATE properties SET status = 'sold' WHERE property_id = ? AND status = 'owned'",
                (property_id,),
            )
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"Property #{property_id} was just sold by someone else.")
            return
        await self.credit(str(interaction.user.id), payout, "property",
                          f"Sold property #{property_id}")
        log_action("property", "sell", str(interaction.user.id), property=property_id)
        embed = success("Sold", f"The state bought **{prop['property_type']}** for {ovi(payout)}.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @property_group.command(name="list", description="Property register")
    @app_commands.describe(user="Owner to look up (defaults to you)")
    async def property_list(self, interaction: discord.Interaction,
                            user: discord.Member = None):
        target = user or interaction.user
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT property_id, property_type, location, value FROM properties "
                "WHERE owner_id = ? AND status = 'owned' ORDER BY property_id LIMIT 12",
                (str(target.id),),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title=f"🏘️ Holdings — {target.display_name}", color=COLOR_GOLD)
        if not rows:
            embed.description = "No property held. `/property buy` opens the register."
        total = 0
        for property_id, kind, location, value in rows:
            total += value
            embed.add_field(name=f"#{property_id} {kind}", value=f"{location}\n{ovi(value)}")
        embed.add_field(name="Assessed total", value=ovi(total))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @property_group.command(name="info", description="Read one deed")
    @app_commands.describe(property_id="Property to inspect")
    async def property_info(self, interaction: discord.Interaction, property_id: int):
        prop = await self._get_property(property_id)
        if prop is None:
            await self.fail(interaction, f"No property #{property_id} exists.")
            return
        embed = DraviaEmbed(title=f"🏘️ {prop['property_type']} #{prop['property_id']}",
                            color=COLOR_GOLD)
        embed.add_field(name="Owner",
                        value=f"<@{prop['owner_id']}>" if prop["owner_id"] else "—", inline=True)
        embed.add_field(name="Location", value=prop["location"] or "—", inline=True)
        embed.add_field(name="Status", value=prop["status"], inline=True)
        embed.add_field(name="Assessed value", value=ovi(prop["value"]), inline=True)
        embed.add_field(name="Registered",
                        value=stamp(prop["built_at"]) if prop["built_at"] else "—", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @property_group.command(name="upgrade", description="Improve a property (5,000 Ovi → +7,500 value)")
    @app_commands.describe(property_id="Property to improve")
    async def property_upgrade(self, interaction: discord.Interaction, property_id: int):
        prop = await self._get_property(property_id)
        if prop is None:
            await self.fail(interaction, f"No property #{property_id} exists.")
            return
        if prop["status"] != "owned":
            await self.fail(interaction, f"Property #{property_id} is **{prop['status']}**.")
            return
        if not self._must_own(interaction, prop):
            await self.fail(interaction, "That property is not yours to improve.")
            return
        if not await self.debit(str(interaction.user.id), UPGRADE_COST, "property",
                                f"Upgrade #{property_id}"):
            await self.fail(interaction,
                            f"An upgrade costs {ovi(UPGRADE_COST)} — you cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE properties SET value = value + ? WHERE property_id = ?",
                             (UPGRADE_VALUE, property_id))
            await db.commit()
            async with db.execute("SELECT value FROM properties WHERE property_id = ?",
                                  (property_id,)) as cur:
                new_value = (await cur.fetchone())[0]
        log_action("property", "upgrade", str(interaction.user.id), property=property_id)
        embed = success("Works completed",
                        f"**{prop['property_type']}** is now worth {ovi(new_value)}.")
        embed.add_field(name="Cost", value=ovi(UPGRADE_COST))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @property_group.command(name="deed", description="Gift property to another citizen")
    @app_commands.describe(property_id="Property to transfer", new_owner="Who receives it")
    async def property_deed(self, interaction: discord.Interaction, property_id: int,
                            new_owner: discord.Member):
        prop = await self._get_property(property_id)
        if prop is None:
            await self.fail(interaction, f"No property #{property_id} exists.")
            return
        if prop["status"] != "owned" or not self._must_own(interaction, prop):
            await self.fail(interaction, "That property is not yours to transfer.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE properties SET owner_id = ? WHERE property_id = ?",
                             (str(new_owner.id), property_id))
            await db.commit()
        log_action("property", "deed", str(interaction.user.id),
                   property=property_id, to=str(new_owner.id))
        embed = success("Deed transferred",
                        f"**{prop['property_type']}** now belongs to **{new_owner.display_name}**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @property_group.command(name="market", description="Registry totals")
    async def property_market(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT property_type, COUNT(*), COALESCE(SUM(value), 0) "
                "FROM properties WHERE status = 'owned' GROUP BY property_type"
            ) as cur:
                rows = await cur.fetchall()
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(value), 0) FROM properties WHERE status = 'owned'"
            ) as cur:
                parcels, total = await cur.fetchone()
            async with db.execute(
                "SELECT COUNT(*) FROM properties WHERE status = 'sold'"
            ) as cur:
                sold = (await cur.fetchone())[0]
        embed = DraviaEmbed(title="🏘️ Property Market", color=COLOR_GOLD)
        for kind, count, value in rows:
            embed.add_field(name=kind, value=f"{count} held · {ovi(value)}", inline=True)
        if not rows:
            embed.description = "No property is currently held."
        embed.add_field(name="Parcels held", value=str(parcels), inline=True)
        embed.add_field(name="Total assessed", value=ovi(total), inline=True)
        embed.add_field(name="Sold to state", value=str(sold), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Property(bot))
