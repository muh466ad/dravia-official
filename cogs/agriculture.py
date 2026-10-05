"""Dravia State Bot - Agriculture, Fishing & Environment

Tables: `farms`, `crops`, `fishing_boats`, `environmental_reports`. Farmers
plant and harvest on a schedule, boat owners fish on an hourly cooldown, and
citizens file pollution reports that Ministers resolve. Dates render through
`stamp()`; readiness is compared inside SQLite so no timezone leaks into the
check.
"""
import random

import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, now, ovi, success, warning
from utils.checks import requires_minister
from utils.validation import text, whole_number

#: crop_type -> (days to mature, Ovi per unit at market).
CROPS = {
    "Wheat": (1, 40),
    "Corn": (2, 45),
    "Rice": (2, 60),
    "Vegetables": (1, 50),
    "Fruit": (3, 70),
}

#: Farm pricing and plant costs.
PER_ACRE = 500
SEED_COST = 50
MAX_ACRES = 10
MAX_SEEDS = 20

#: Fishing economics — an hourly catch of up to capacity × CATCH_VALUE.
CATCH_VALUE = 10
FISHING_COOLDOWN = 3600

BOAT_TYPES = {
    "Rowboat": (1500, 20),
    "Skiff": (3000, 40),
    "Trawler": (6000, 80),
}

POLLUTION_KINDS = ["Industrial waste", "Airborne emissions", "Water contamination",
                   "Littering", "Noise"]
SEVERITIES = ["Low", "Medium", "High", "Critical"]

_FARM_COLS = ("farm_id", "owner_id", "location", "size", "created_at")
_BOAT_COLS = ("boat_id", "owner_id", "boat_type", "capacity", "purchased_at")
_REPORT_COLS = ("report_id", "reporter_id", "location", "pollution_type",
                "severity", "reported_at", "status")


class Agriculture(DraviaCog):
    """Farming, fishing and environmental commands."""

    group_name = "business"
    farm_group = app_commands.Group(name="farm", description="Land and crops")
    fishing_group = app_commands.Group(name="fishing", description="Boats and catches")
    env_group = app_commands.Group(name="env", description="Environmental reports")

    # ------------------------------------------------------------ helpers
    async def _get_farm(self, farm_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM farms WHERE farm_id = ?", (farm_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_FARM_COLS, row)) if row else None

    async def _get_boat(self, boat_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM fishing_boats WHERE boat_id = ?", (boat_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_BOAT_COLS, row)) if row else None

    def _own(self, interaction, owner_id) -> bool:
        return str(owner_id) == str(interaction.user.id)

    # -------------------------------------------------------------- /farm
    @farm_group.command(name="claim", description="Buy land and start a farm")
    @app_commands.describe(location="Where the land is", acres="Size (1-10, 500 Ovi each)")
    @handles_validation
    async def farm_claim(self, interaction: discord.Interaction, location: str,
                         acres: int = 2):
        location = text(location, field="Location", maximum=60)
        acres = whole_number(acres, field="Acres", minimum=1, maximum=MAX_ACRES)
        cost = acres * PER_ACRE
        user_id = str(interaction.user.id)
        if not await self.debit(user_id, cost, "farm", f"Land at {location}"):
            await self.fail(interaction,
                            f"{acres} acre(s) cost {ovi(cost)} — you cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO farms (owner_id, location, size, created_at) "
                "VALUES (?, ?, ?, date('now'))",
                (user_id, location, acres),
            )
            await db.commit()
            async with db.execute("SELECT MAX(farm_id) FROM farms") as cur:
                farm_id = (await cur.fetchone())[0]
        log_action("farm", "claim", user_id, farm=farm_id, acres=acres)
        embed = success("Land registered", f"{acres} acre(s) at **{location}** are yours.")
        embed.add_field(name="Farm ID", value=f"#{farm_id}")
        embed.add_field(name="Cost", value=ovi(cost))
        embed.add_field(name="Next", value="Plant with `/farm plant`.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @farm_group.command(name="plant", description="Sow a crop")
    @app_commands.describe(farm_id="Your farm", crop_type="What to grow",
                           quantity="Seeds (1-20, 50 Ovi each)")
    @app_commands.choices(crop_type=[app_commands.Choice(name=c, value=c) for c in CROPS])
    async def farm_plant(self, interaction: discord.Interaction, farm_id: int,
                         crop_type: str, quantity: int = 1):
        farm = await self._get_farm(farm_id)
        if farm is None:
            await self.fail(interaction, f"No farm #{farm_id} exists.")
            return
        if not self._own(interaction, farm["owner_id"]):
            await self.fail(interaction, "That farm is not yours.")
            return
        if crop_type not in CROPS:
            await self.fail(interaction, f"Unknown crop **{crop_type}**.")
            return
        quantity = whole_number(quantity, field="Seeds", minimum=1, maximum=MAX_SEEDS)
        cost = quantity * SEED_COST
        if not await self.debit(str(interaction.user.id), cost, "farm",
                                f"Seeds: {crop_type}"):
            await self.fail(interaction, f"{quantity} seed(s) cost {ovi(cost)} — you cannot afford it.")
            return
        days = CROPS[crop_type][0]
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO crops (farm_id, crop_type, quantity, planted_at, harvest_at) "
                "VALUES (?, ?, ?, date('now'), date('now', ?))",
                (farm_id, crop_type, quantity, f"+{days} days"),
            )
            await db.commit()
        log_action("farm", "plant", str(interaction.user.id),
                   farm=farm_id, crop=crop_type, quantity=quantity)
        embed = success("Sown", f"{quantity} × **{crop_type}** planted.")
        embed.add_field(name="Matures", value=f"{days} day(s) from now")
        embed.add_field(name="Seed cost", value=ovi(cost))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @farm_group.command(name="status", description="Farm and crop progress")
    @app_commands.describe(farm_id="Farm to inspect")
    async def farm_status(self, interaction: discord.Interaction, farm_id: int):
        farm = await self._get_farm(farm_id)
        if farm is None:
            await self.fail(interaction, f"No farm #{farm_id} exists.")
            return
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT crop_id, crop_type, quantity, harvest_at FROM crops "
                "WHERE farm_id = ? ORDER BY harvest_at",
                (farm_id,),
            ) as cur:
                crops = await cur.fetchall()
            async with db.execute(
                "SELECT COUNT(*) FROM crops WHERE farm_id = ? "
                "AND date(harvest_at) <= date('now')",
                (farm_id,),
            ) as cur:
                ready = (await cur.fetchone())[0]
        embed = DraviaEmbed(title=f"🌾 Farm #{farm['farm_id']} — {farm['location']}",
                            color=COLOR_GOLD)
        embed.add_field(name="Size", value=f"{farm['size']} acre(s)", inline=True)
        embed.add_field(name="Registered", value=stamp(farm["created_at"]), inline=True)
        embed.add_field(name="Ready to harvest", value=str(ready), inline=True)
        if not crops:
            embed.add_field(name="Crops", value="Bare fields — `/farm plant` to sow.")
        for crop_id, crop_type, quantity, harvest_at in crops:
            embed.add_field(name=f"#{crop_id} {crop_type} ×{quantity}",
                            value=f"harvest from {stamp(harvest_at)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @farm_group.command(name="harvest", description="Gather every mature crop")
    @app_commands.describe(farm_id="Farm to harvest")
    async def farm_harvest(self, interaction: discord.Interaction, farm_id: int):
        farm = await self._get_farm(farm_id)
        if farm is None:
            await self.fail(interaction, f"No farm #{farm_id} exists.")
            return
        if not self._own(interaction, farm["owner_id"]):
            await self.fail(interaction, "That farm is not yours.")
            return
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT crop_id, crop_type, quantity FROM crops "
                "WHERE farm_id = ? AND date(harvest_at) <= date('now')",
                (farm_id,),
            ) as cur:
                mature = await cur.fetchall()
            if not mature:
                await self.fail(interaction, "Nothing on this farm is ready yet.")
                return
            payout = sum(quantity * CROPS.get(crop_type, (0, 0))[1]
                         for _, crop_type, quantity in mature)
            ids = [crop_id for crop_id, _, _ in mature]
            await db.execute(
                f"DELETE FROM crops WHERE crop_id IN ({','.join('?' * len(ids))})", ids
            )
            await db.commit()
        await self.credit(str(interaction.user.id), payout, "farm",
                          f"Harvest of farm #{farm_id}")
        log_action("farm", "harvest", str(interaction.user.id),
                   farm=farm_id, payout=payout, crops=len(mature))
        embed = success("Harvest in", f"{len(mature)} crop lot(s) sold for {ovi(payout)}.")
        for _, crop_type, quantity in mature:
            embed.add_field(name=crop_type, value=f"×{quantity}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @farm_group.command(name="list", description="Your land")
    async def farm_list(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT farm_id, location, size FROM farms WHERE owner_id = ? "
                "ORDER BY farm_id LIMIT 12",
                (str(interaction.user.id),),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title=f"🌾 Land — {interaction.user.display_name}", color=COLOR_GOLD)
        if not rows:
            embed.description = "You hold no land. `/farm claim` buys the first plot."
        for farm_id, location, size in rows:
            embed.add_field(name=f"#{farm_id} {location}", value=f"{size} acre(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @farm_group.command(name="sell", description="Sell a farm back to the state (crops must be cleared)")
    @app_commands.describe(farm_id="Farm to sell")
    async def farm_sell(self, interaction: discord.Interaction, farm_id: int):
        farm = await self._get_farm(farm_id)
        if farm is None:
            await self.fail(interaction, f"No farm #{farm_id} exists.")
            return
        if not self._own(interaction, farm["owner_id"]):
            await self.fail(interaction, "That farm is not yours.")
            return
        payout = farm["size"] * PER_ACRE * 3 // 4
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT 1 FROM crops WHERE farm_id = ? LIMIT 1", (farm_id,)
            ) as cur:
                if await cur.fetchone():
                    await self.fail(interaction,
                                    "Harvest the crops first — `/farm harvest`.")
                    return
            cur = await db.execute("DELETE FROM farms WHERE farm_id = ?", (farm_id,))
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"Farm #{farm_id} is already gone.")
            return
        await self.credit(str(interaction.user.id), payout, "farm", f"Sold farm #{farm_id}")
        log_action("farm", "sell", str(interaction.user.id), farm=farm_id, payout=payout)
        embed = success("Land sold", f"The state bought farm #{farm_id} for {ovi(payout)}.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ----------------------------------------------------------- /fishing
    @fishing_group.command(name="buy", description="Buy a boat")
    @app_commands.describe(boat_type="Hull to buy")
    @app_commands.choices(boat_type=[app_commands.Choice(
        name=f"{k} ({v[0]:,} Ovi · catch {v[1]})", value=k)
        for k, v in BOAT_TYPES.items()])
    async def fishing_buy(self, interaction: discord.Interaction, boat_type: str = "Rowboat"):
        if boat_type not in BOAT_TYPES:
            await self.fail(interaction, f"Unknown hull **{boat_type}**.")
            return
        price, capacity = BOAT_TYPES[boat_type]
        user_id = str(interaction.user.id)
        if not await self.debit(user_id, price, "fishing", f"Bought {boat_type}"):
            await self.fail(interaction,
                            f"A **{boat_type}** costs {ovi(price)} — you cannot afford it.")
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO fishing_boats (owner_id, boat_type, capacity, purchased_at) "
                "VALUES (?, ?, ?, date('now'))",
                (user_id, boat_type, capacity),
            )
            await db.commit()
            async with db.execute("SELECT MAX(boat_id) FROM fishing_boats") as cur:
                boat_id = (await cur.fetchone())[0]
        log_action("fishing", "buy", user_id, boat=boat_id, boat_type=boat_type)
        embed = success("Launch your boat", f"**{boat_type}** is seaworthy.")
        embed.add_field(name="Boat ID", value=f"#{boat_id}")
        embed.add_field(name="Capacity", value=f"catch up to {capacity * CATCH_VALUE} Ovi")
        embed.add_field(name="Next", value="`/fishing fish` once an hour.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fishing_group.command(name="fish", description="Cast nets (hourly)")
    @app_commands.describe(boat_id="Boat to sail")
    async def fishing_fish(self, interaction: discord.Interaction, boat_id: int):
        boat = await self._get_boat(boat_id)
        if boat is None:
            await self.fail(interaction, f"No boat #{boat_id} exists.")
            return
        if not self._own(interaction, boat["owner_id"]):
            await self.fail(interaction, "That boat is not yours.")
            return
        user_id = str(interaction.user.id)
        remaining = await self.db.cooldown_remaining(user_id, "fishing")
        if remaining > 0:
            await self.fail(interaction,
                            f"The nets need {remaining / 60:.0f} more minute(s) to dry.")
            return
        catch = random.randint(1, boat["capacity"]) * CATCH_VALUE
        await self.db.set_expiring_cooldown(user_id, "fishing", FISHING_COOLDOWN)
        await self.credit(user_id, catch, "fishing", f"Catch from boat #{boat_id}")
        log_action("fishing", "fish", user_id, boat=boat_id, catch=catch)
        embed = success("Bumper catch", f"Your **{boat['boat_type']}** landed {ovi(catch)}.")
        embed.add_field(name="Next cast", value="in 60 minutes")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fishing_group.command(name="fleet", description="Your boats")
    async def fishing_fleet(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT boat_id, boat_type, capacity, purchased_at FROM fishing_boats "
                "WHERE owner_id = ? ORDER BY boat_id LIMIT 10",
                (str(interaction.user.id),),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title=f"⚓ Fleet — {interaction.user.display_name}", color=COLOR_GOLD)
        if not rows:
            embed.description = "No boats. `/fishing buy` launches the first."
        for boat_id, boat_type, capacity, purchased_at in rows:
            embed.add_field(name=f"#{boat_id} {boat_type}",
                            value=f"capacity {capacity} · bought {stamp(purchased_at)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fishing_group.command(name="sell", description="Sell a boat (75% of price)")
    @app_commands.describe(boat_id="Boat to sell")
    async def fishing_sell(self, interaction: discord.Interaction, boat_id: int):
        boat = await self._get_boat(boat_id)
        if boat is None:
            await self.fail(interaction, f"No boat #{boat_id} exists.")
            return
        if not self._own(interaction, boat["owner_id"]):
            await self.fail(interaction, "That boat is not yours.")
            return
        price = BOAT_TYPES.get(boat["boat_type"], (1000, 10))[0]
        payout = price * 3 // 4
        async with await self.db.get_connection() as db:
            cur = await db.execute("DELETE FROM fishing_boats WHERE boat_id = ?", (boat_id,))
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"Boat #{boat_id} is already gone.")
            return
        await self.credit(str(interaction.user.id), payout, "fishing", f"Sold boat #{boat_id}")
        log_action("fishing", "sell", str(interaction.user.id), boat=boat_id, payout=payout)
        embed = success("Boat sold", f"The harbour bought your {boat['boat_type']} for {ovi(payout)}.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --------------------------------------------------------------- /env
    @env_group.command(name="report", description="File a pollution report")
    @app_commands.describe(location="Where", pollution_type="What kind",
                           severity="How bad")
    @app_commands.choices(
        pollution_type=[app_commands.Choice(name=k, value=k) for k in POLLUTION_KINDS],
        severity=[app_commands.Choice(name=s, value=s) for s in SEVERITIES],
    )
    @handles_validation
    async def env_report(self, interaction: discord.Interaction, location: str,
                         pollution_type: str = POLLUTION_KINDS[0],
                         severity: str = "Medium"):
        location = text(location, field="Location", maximum=80)
        pollution_type = pollution_type if pollution_type in POLLUTION_KINDS else POLLUTION_KINDS[0]
        severity = severity if severity in SEVERITIES else "Medium"
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO environmental_reports (reporter_id, location, pollution_type, "
                "severity, reported_at, status) VALUES (?, ?, ?, ?, ?, 'open')",
                (str(interaction.user.id), location, pollution_type, severity, now()),
            )
            await db.commit()
            async with db.execute(
                "SELECT MAX(report_id) FROM environmental_reports"
            ) as cur:
                report_id = (await cur.fetchone())[0]
        log_action("env", "report", str(interaction.user.id),
                   report=report_id, severity=severity, location=location)
        embed = warning("Report filed",
                        f"**{severity}** {pollution_type.lower()} at **{location}**.")
        embed.add_field(name="Report ID", value=f"#{report_id}")
        embed.add_field(name="Next", value="Ministers inspect with `/env open`.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @env_group.command(name="open", description="Open reports (Minister)")
    @requires_minister
    async def env_open(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT report_id, location, pollution_type, severity, reported_at "
                "FROM environmental_reports WHERE status = 'open' "
                "ORDER BY report_id DESC LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🌿 Open Environmental Reports", color=COLOR_GOLD)
        if not rows:
            embed.description = "Nothing outstanding — the air is clean."
        for report_id, location, pollution_type, severity, reported_at in rows:
            embed.add_field(name=f"#{report_id} {severity} — {location}",
                            value=f"{pollution_type} · filed {stamp(reported_at)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @env_group.command(name="resolve", description="Close a report (Minister)")
    @app_commands.describe(report_id="Report to close")
    @requires_minister
    async def env_resolve(self, interaction: discord.Interaction, report_id: int):
        async with await self.db.get_connection() as db:
            cur = await db.execute(
                "UPDATE environmental_reports SET status = 'resolved' "
                "WHERE report_id = ? AND status = 'open'",
                (report_id,),
            )
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"No open report #{report_id} exists.")
            return
        log_action("env", "resolve", str(interaction.user.id), report=report_id)
        embed = success("Report closed", f"Report #{report_id} has been actioned.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @env_group.command(name="stats", description="Pollution picture across Dravia")
    async def env_stats(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT severity, COUNT(*) FROM environmental_reports "
                "WHERE status = 'open' GROUP BY severity"
            ) as cur:
                by_severity = dict(await cur.fetchall())
            async with db.execute(
                "SELECT COUNT(*) FROM environmental_reports WHERE status = 'resolved'"
            ) as cur:
                resolved = (await cur.fetchone())[0]
        embed = DraviaEmbed(title="🌿 Environmental Standing", color=COLOR_GOLD)
        for severity in SEVERITIES:
            embed.add_field(name=f"Open · {severity}",
                            value=str(by_severity.get(severity, 0)), inline=True)
        embed.add_field(name="Resolved", value=str(resolved), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Agriculture(bot))
