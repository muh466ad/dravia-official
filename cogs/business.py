"""Dravia State Bot - Business System"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from utils.calendar import dravian_timestamp, stamp
from utils.checks import requires_minister
from database import Database
from utils.logger import tx_log, audit_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

LICENSES = {
    "shop": {"name": "Shop", "fee": 500, "monthly": 300, "products_per_day": 10},
    "regular": {"name": "Regular Business", "fee": 1000, "monthly": 600, "products_per_day": 20},
    "large": {"name": "Large Business", "fee": 2000, "monthly": 1200, "products_per_day": 30},
    "newspaper": {"name": "Newspaper", "fee": 700, "monthly": 450, "products_per_day": 10},
    "insurance": {"name": "Insurance Company", "fee": 1000, "monthly": 600, "products_per_day": 20},
    "event": {"name": "Event Company", "fee": 2000, "monthly": 1200, "products_per_day": 20},
    "bank": {"name": "Private Bank", "fee": 3000, "monthly": 1800, "products_per_day": 30},
    "gambling": {"name": "Gambling License", "fee": 5000, "monthly": 1000, "products_per_day": 30},
}

FACILITIES = {
    1: {"name": "Small Workshop", "cost": 1000, "points": 10},
    2: {"name": "Medium Plant", "cost": 3000, "points": 30},
    3: {"name": "Large Plant", "cost": 7500, "points": 75},
    4: {"name": "Industrial Complex", "cost": 15000, "points": 150},
}

# Raw materials and point values (Part 5)
RAW_MATERIALS = {
    "Wheat": 1, "Corn": 1, "Vegetables": 2, "Fruit": 2, "Milk": 2, "Eggs": 2,
    "Meat": 3, "Honey": 3, "Clay": 2, "Wool": 2, "Timber": 3, "Stone": 3,
    "Cotton": 2, "Leather": 3,
}

class Business(commands.Cog):
    """Business commands for Dravia."""
    
    biz_group = app_commands.Group(name="business", description="Business registration and management")
    fac_group = app_commands.Group(name="facility", description="Production facilities")
    transport_group = app_commands.Group(name="transport", description="State transport network")
    utility_group = app_commands.Group(name="utility", description="Energy and telecom infrastructure")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    async def get_business(self, name: str):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM businesses WHERE lower(name) = lower(?)", (name,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def owned_business(self, user_id: str):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM businesses WHERE owner_id = ? AND is_active = 1", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    @biz_group.command(name="register", description="Register a new business")
    @app_commands.describe(name="Business name", description="What it does")
    @app_commands.choices(license_type=[
            app_commands.Choice(name="Shop (🪙500 + 300/mo)", value="shop"),
            app_commands.Choice(name="Regular Business (🪙1,000 + 600/mo)", value="regular"),
            app_commands.Choice(name="Large Business (🪙2,000 + 1,200/mo)", value="large"),
            app_commands.Choice(name="Newspaper (🪙700 + 450/mo)", value="newspaper"),
            app_commands.Choice(name="Insurance Company (🪙1,000 + 600/mo)", value="insurance"),
            app_commands.Choice(name="Event Company (🪙2,000 + 1,200/mo)", value="event"),
            app_commands.Choice(name="Private Bank (🪙3,000 + 1,800/mo)", value="bank"),
            app_commands.Choice(name="Gambling License (🪙5,000 + 1,000/mo)", value="gambling"),
        ])
    async def business_register(
        self, interaction: discord.Interaction, name: str, license_type: str, description: str = ""
    ):
        user_id = str(interaction.user.id)
        if await self.get_business(name):
            await interaction.response.send_message("❌ A business with that name already exists.", ephemeral=True)
            return
        if await self.owned_business(user_id):
            await interaction.response.send_message(
                "❌ You already own an active business. Close it first.", ephemeral=True
            )
            return

        license_info = LICENSES[license_type]
        balance = await self.db.get_balance(user_id)
        if balance < license_info["fee"]:
            await interaction.response.send_message(
                f"❌ License fee is 🪙 {license_info['fee']:,}. You have 🪙 {balance:,}.",
                ephemeral=True,
            )
            return

        await self.db.remove_balance(user_id, license_info["fee"], "license_fee", f"{license_info['name']} license")
        renewal_due = (datetime.now() + timedelta(days=30)).isoformat()

        async with await self.db.get_connection() as db:
            await db.execute(
                """INSERT INTO businesses (name, owner_id, business_type, license_type, description,
                   registered_at, is_active, monthly_renewal_due) VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (name, user_id, license_info["name"], license_type, description,
                 datetime.now().isoformat(), renewal_due),
            )
            await db.commit()

        tx_log.info("Business registered: %s by %s (license=%s)", name, user_id, license_type)
        embed = discord.Embed(
            title="🏢 Business Registered",
            description=f"**{name}** is now a licensed Dravian enterprise!",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="License", value=license_info["name"], inline=True)
        embed.add_field(name="Fee Paid", value=f"🪙 **{license_info['fee']:,}**", inline=True)
        embed.add_field(name="Monthly Renewal", value=f"🪙 **{license_info['monthly']:,}**", inline=True)
        embed.add_field(name="Products/Day", value=f"**{license_info['products_per_day']}**", inline=True)
        embed.add_field(name="Next Renewal", value=f"<t:{dravian_timestamp(datetime.now() + timedelta(days=30))}:D>", inline=True)
        embed.set_footer(text="Republic of Dravia | Ministry of Commerce")
        await interaction.response.send_message(embed=embed)

    @biz_group.command(name="list", description="List all registered businesses")
    async def business_list(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT name, owner_id, license_type, is_active FROM businesses ORDER BY registered_at DESC LIMIT 15"
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title="🏢 Registered Businesses", color=COLOR_GOLD)
        if not rows:
            embed.description = "No businesses registered yet. Use `/business register`!"
        else:
            for r in rows:
                status = "✅" if r["is_active"] else "❌"
                embed.add_field(
                    name=f"{status} {r['name']}",
                    value=f"{LICENSES.get(r['license_type'], {}).get('name', r['license_type'])} | <@{r['owner_id']}>",
                    inline=False,
                )
        embed.set_footer(text="Republic of Dravia | Ministry of Commerce")
        await interaction.response.send_message(embed=embed)

    @biz_group.command(name="info", description="View business details")
    @app_commands.describe(name="Business name")
    async def business_info(self, interaction: discord.Interaction, name: str):
        biz = await self.get_business(name)
        if not biz:
            await interaction.response.send_message("❌ No business with that name.", ephemeral=True)
            return

        license_info = LICENSES.get(biz["license_type"], {})
        facility = FACILITIES.get(biz["facility_tier"], None)

        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM business_employees WHERE business_id = ?", (biz["id"],)
            ) as cursor:
                employees = (await cursor.fetchone())[0]

        embed = discord.Embed(title=f"🏢 {biz['name']}", description=biz["description"] or "", color=COLOR_ACCENT)
        embed.add_field(name="Owner", value=f"<@{biz['owner_id']}>", inline=True)
        embed.add_field(name="License", value=license_info.get("name", biz["license_type"]), inline=True)
        embed.add_field(name="Status", value="✅ Active" if biz["is_active"] else "❌ Closed", inline=True)
        embed.add_field(name="Employees", value=f"**{employees}**", inline=True)
        embed.add_field(name="Facility", value=facility["name"] if facility else "None", inline=True)
        embed.add_field(name="Daily Points", value=f"**{biz['daily_points']}**", inline=True)
        embed.add_field(name="Monthly Renewal", value=f"🪙 **{license_info.get('monthly', 0):,}**", inline=True)
        embed.set_footer(text="Republic of Dravia | Ministry of Commerce")
        await interaction.response.send_message(embed=embed)

    @biz_group.command(name="renew", description="Pay your monthly business renewal")
    @app_commands.describe(name="Business name")
    async def business_renew(self, interaction: discord.Interaction, name: str):
        user_id = str(interaction.user.id)
        biz = await self.get_business(name)
        if not biz or biz["owner_id"] != user_id:
            await interaction.response.send_message("❌ You don't own that business.", ephemeral=True)
            return

        license_info = LICENSES.get(biz["license_type"], {})
        fee = license_info.get("monthly", 0)
        balance = await self.db.get_balance(user_id)
        if balance < fee:
            await interaction.response.send_message(
                f"❌ Renewal fee is 🪙 {fee:,}. You have 🪙 {balance:,}. Unpaid renewals close the business.",
                ephemeral=True,
            )
            return

        await self.db.remove_balance(user_id, fee, "business_renewal", f"{biz['name']} renewal")
        new_due = (datetime.now() + timedelta(days=30)).isoformat()
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE businesses SET monthly_renewal_due = ?, is_active = 1 WHERE id = ?", (new_due, biz["id"])
            )
            await db.commit()

        tx_log.info("Business renewal: %s by %s fee=%s", biz["name"], user_id, fee)
        embed = discord.Embed(title="✅ License Renewed", description=f"**{biz['name']}**", color=COLOR_GOLD)
        embed.add_field(name="Fee", value=f"🪙 **{fee:,}**", inline=True)
        embed.add_field(name="Next Due", value=f"<t:{dravian_timestamp(datetime.now() + timedelta(days=30))}:D>", inline=True)
        await interaction.response.send_message(embed=embed)

    @biz_group.command(name="close", description="Close your business")
    @app_commands.describe(name="Business name")
    async def business_close(self, interaction: discord.Interaction, name: str):
        user_id = str(interaction.user.id)
        biz = await self.get_business(name)
        if not biz or biz["owner_id"] != user_id:
            await interaction.response.send_message("❌ You don't own that business.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            await db.execute("UPDATE businesses SET is_active = 0 WHERE id = ?", (biz["id"],))
            await db.execute("DELETE FROM business_employees WHERE business_id = ?", (biz["id"],))
            await db.commit()

        audit_log.info("Business closed: %s by %s", biz["name"], user_id)
        await interaction.response.send_message(f"🏢 **{biz['name']}** has been closed.", ephemeral=True)

    @biz_group.command(name="hire", description="Hire an employee")
    @app_commands.describe(business="Business name", user="Employee", role="Role", salary="Weekly salary")
    async def business_hire(
        self, interaction: discord.Interaction, business: str, user: discord.Member, role: str, salary: int
    ):
        user_id = str(interaction.user.id)
        biz = await self.get_business(business)
        if not biz or biz["owner_id"] != user_id:
            await interaction.response.send_message("❌ You don't own that business.", ephemeral=True)
            return
        if salary < 0:
            await interaction.response.send_message("❌ Salary must be non-negative.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO business_employees (business_id, user_id, role, salary, hired_at) VALUES (?, ?, ?, ?, ?)",
                (biz["id"], str(user.id), role, salary, datetime.now().isoformat()),
            )
            await db.commit()

        embed = discord.Embed(
            title="🤝 Hired",
            description=f"{user.mention} hired at **{biz['name']}** as **{role}**",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Weekly Salary", value=f"🪙 **{salary:,}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @biz_group.command(name="fire", description="Fire an employee")
    @app_commands.describe(business="Business name", user="Employee")
    async def business_fire(self, interaction: discord.Interaction, business: str, user: discord.Member):
        user_id = str(interaction.user.id)
        biz = await self.get_business(business)
        if not biz or biz["owner_id"] != user_id:
            await interaction.response.send_message("❌ You don't own that business.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            await db.execute(
                "DELETE FROM business_employees WHERE business_id = ? AND user_id = ?",
                (biz["id"], str(user.id)),
            )
            await db.commit()

        await interaction.response.send_message(f"🚪 {user.mention} dismissed from **{biz['name']}**.", ephemeral=True)

    @biz_group.command(name="employees", description="List your employees")
    @app_commands.describe(business="Business name")
    async def business_employees(self, interaction: discord.Interaction, business: str):
        biz = await self.get_business(business)
        if not biz:
            await interaction.response.send_message("❌ No business with that name.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT user_id, role, salary FROM business_employees WHERE business_id = ?", (biz["id"],)
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title=f"👥 {biz['name']} — Employees", color=COLOR_ACCENT)
        if not rows:
            embed.description = "No employees hired."
        else:
            for r in rows:
                embed.add_field(
                    name=f"<@{r['user_id']}> — {r['role']}",
                    value=f"🪙 **{r['salary']:,}**/week",
                    inline=True,
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fac_group.command(name="build", description="Build a production facility")
    @app_commands.describe(business="Business name", tier="Facility tier (1-4)")
    @app_commands.choices(tier=[
            app_commands.Choice(name="I - Small Workshop (🪙1,000, 10 pts/day)", value=1),
            app_commands.Choice(name="II - Medium Plant (🪙3,000, 30 pts/day)", value=2),
            app_commands.Choice(name="III - Large Plant (🪙7,500, 75 pts/day)", value=3),
            app_commands.Choice(name="IV - Industrial Complex (🪙15,000, 150 pts/day)", value=4),
        ])
    async def facility_build(self, interaction: discord.Interaction, business: str, tier: int):
        user_id = str(interaction.user.id)
        biz = await self.get_business(business)
        if not biz or biz["owner_id"] != user_id:
            await interaction.response.send_message("❌ You don't own that business.", ephemeral=True)
            return
        if biz["facility_tier"] > 0:
            await interaction.response.send_message(
                f"⚠️ You already have a **{FACILITIES.get(biz['facility_tier'], {}).get('name', 'facility')}**. Use `/facility upgrade`.",
                ephemeral=True,
            )
            return

        facility = FACILITIES[tier]
        balance = await self.db.get_balance(user_id)
        if balance < facility["cost"]:
            await interaction.response.send_message(
                f"❌ Construction costs 🪙 {facility['cost']:,}. You have 🪙 {balance:,}.", ephemeral=True
            )
            return

        await self.db.remove_balance(user_id, facility["cost"], "construction", f"Build {facility['name']}")
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE businesses SET facility_tier = ?, daily_points = ? WHERE id = ?",
                (tier, facility["points"], biz["id"]),
            )
            await db.commit()

        embed = discord.Embed(
            title="🏗️ Facility Built",
            description=f"**{facility['name']}** constructed for **{biz['name']}**",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Cost", value=f"🪙 **{facility['cost']:,}**", inline=True)
        embed.add_field(name="Capacity", value=f"**{facility['points']} pts/day**", inline=True)
        await interaction.response.send_message(embed=embed)

    @fac_group.command(name="upgrade", description="Upgrade your production facility")
    @app_commands.describe(business="Business name")
    async def facility_upgrade(self, interaction: discord.Interaction, business: str):
        user_id = str(interaction.user.id)
        biz = await self.get_business(business)
        if not biz or biz["owner_id"] != user_id:
            await interaction.response.send_message("❌ You don't own that business.", ephemeral=True)
            return
        next_tier = biz["facility_tier"] + 1
        if next_tier > 4:
            await interaction.response.send_message("✅ You already have the maximum tier facility.", ephemeral=True)
            return

        facility = FACILITIES[next_tier]
        balance = await self.db.get_balance(user_id)
        if balance < facility["cost"]:
            await interaction.response.send_message(
                f"❌ Upgrade costs 🪙 {facility['cost']:,}. You have 🪙 {balance:,}.", ephemeral=True
            )
            return

        await self.db.remove_balance(user_id, facility["cost"], "construction", f"Upgrade to {facility['name']}")
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE businesses SET facility_tier = ?, daily_points = ? WHERE id = ?",
                (next_tier, facility["points"], biz["id"]),
            )
            await db.commit()

        embed = discord.Embed(
            title="⬆️ Facility Upgraded",
            description=f"Now **{facility['name']}** ({facility['points']} pts/day)",
            color=COLOR_GOLD,
        )
        await interaction.response.send_message(embed=embed)

    @fac_group.command(name="status", description="Check facility status")
    @app_commands.describe(business="Business name")
    async def facility_status(self, interaction: discord.Interaction, business: str):
        biz = await self.get_business(business)
        if not biz:
            await interaction.response.send_message("❌ No business with that name.", ephemeral=True)
            return
        facility = FACILITIES.get(biz["facility_tier"])
        embed = discord.Embed(title=f"🏗️ {biz['name']} — Facility", color=COLOR_ACCENT)
        embed.add_field(name="Tier", value=facility["name"] if facility else "None built", inline=True)
        embed.add_field(name="Daily Capacity", value=f"**{biz['daily_points']} pts/day**", inline=True)
        embed.add_field(name="Specialization", value=biz["specialization"] or "None", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="produce", description="Produce goods from raw materials")
    @app_commands.describe(business="Business name", item="Product name", quantity="How many to produce")
    async def produce(self, interaction: discord.Interaction, business: str, item: str, quantity: int):
        user_id = str(interaction.user.id)
        biz = await self.get_business(business)
        if not biz or biz["owner_id"] != user_id:
            await interaction.response.send_message("❌ You don't own that business.", ephemeral=True)
            return
        if biz["facility_tier"] <= 0:
            await interaction.response.send_message("❌ Build a facility first with `/facility build`.", ephemeral=True)
            return
        if quantity <= 0:
            await interaction.response.send_message("❌ Quantity must be positive.", ephemeral=True)
            return

        point_value = RAW_MATERIALS.get(item.title(), 1)
        cost_points = point_value * quantity
        if cost_points > biz["daily_points"]:
            await interaction.response.send_message(
                f"❌ Producing {quantity}× {item} needs {cost_points} pts but your facility capacity is {biz['daily_points']} pts/day.",
                ephemeral=True,
            )
            return

        # Specialization bonus: single product line +10%, two lines +5%
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT product_name FROM business_inventory WHERE business_id = ? AND quantity > 0", (biz["id"],)
            ) as cursor:
                existing_products = {r["product_name"] for r in await cursor.fetchall()}

            bonus = 1.0
            all_products = existing_products | {item.title()}
            if len(all_products) == 1:
                bonus = 1.10
            elif len(all_products) == 2:
                bonus = 1.05

            produced = int(quantity * bonus)
            await db.execute(
                """INSERT INTO business_inventory (business_id, product_name, quantity, point_value)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(business_id, product_name) DO UPDATE SET quantity = quantity + excluded.quantity""",
                (biz["id"], item.title(), produced, point_value),
            )
            await db.execute(
                "UPDATE businesses SET specialization = ? WHERE id = ?",
                (", ".join(sorted(all_products)), biz["id"]),
            )
            await db.commit()

        embed = discord.Embed(
            title="🏭 Production Complete",
            description=f"**{produced}× {item.title()}** produced at **{biz['name']}**",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Points Used", value=f"**{cost_points}/{biz['daily_points']}**", inline=True)
        embed.add_field(name="Specialization Bonus", value=f"**+{(bonus - 1) * 100:.0f}%**", inline=True)
        embed.set_footer(text="Republic of Dravia | Ministry of Commerce")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="inventory", description="Check business inventory")
    @app_commands.describe(business="Business name")
    async def inventory(self, interaction: discord.Interaction, business: str):
        biz = await self.get_business(business)
        if not biz:
            await interaction.response.send_message("❌ No business with that name.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT product_name, quantity, point_value FROM business_inventory WHERE business_id = ? AND quantity > 0",
                (biz["id"],),
            ) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(title=f"📦 {biz['name']} — Inventory", color=COLOR_GOLD)
        if not rows:
            embed.description = "Inventory is empty. Use `/produce`."
        else:
            for r in rows:
                embed.add_field(
                    name=r["product_name"],
                    value=f"Qty: **{r['quantity']}** | Point value: **{r['point_value']}**",
                    inline=True,
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @biz_group.command(name="report", description="File your weekly production report")
    @app_commands.describe(business="Business name")
    async def business_report(self, interaction: discord.Interaction, business: str):
        user_id = str(interaction.user.id)
        biz = await self.get_business(business)
        if not biz or biz["owner_id"] != user_id:
            await interaction.response.send_message("❌ You don't own that business.", ephemeral=True)
            return

        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM business_inventory WHERE business_id = ?", (biz["id"],)
            ) as cursor:
                total_units = (await cursor.fetchone())[0]

        audit_log.info("Production report filed for %s by %s", biz["name"], user_id)
        embed = discord.Embed(
            title="📄 Production Report Filed",
            description=f"**{biz['name']}**",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Units in Stock", value=f"**{total_units}**", inline=True)
        embed.add_field(name="Daily Capacity", value=f"**{biz['daily_points']} pts**", inline=True)
        embed.add_field(name="Filed", value="Monday deadline met", inline=True)
        await interaction.response.send_message(embed=embed)


    # ------------------------------------------------------ transport (Part 23)
    TRANSPORT_KINDS = ["Bus", "Train", "Ferry", "Air"]
    TRAVEL_CLASSES = {"Standard": 1, "First": 2}

    @transport_group.command(name="route", description="Open a route (Minister)")
    @app_commands.describe(kind="Mode of transport", origin="Departure point",
                           destination="Arrival point", price="Standard fare in Ovi")
    @app_commands.choices(kind=[app_commands.Choice(name=k, value=k)
                                for k in ("Bus", "Train", "Ferry", "Air")])
    @requires_minister
    async def transport_route(self, interaction: discord.Interaction, kind: str,
                              origin: str, destination: str, price: int):
        origin = " ".join(origin.split())[:40]
        destination = " ".join(destination.split())[:40]
        if not origin or not destination:
            await interaction.response.send_message(
                "❌ Both ends of the route are required.", ephemeral=True)
            return
        if price < 1 or price > 100000:
            await interaction.response.send_message(
                "❌ Fares run from 1 to 100,000 Ovi.", ephemeral=True)
            return
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO transport_routes (transport_type, origin, destination, price, status) "
                "VALUES (?, ?, ?, ?, 'active')",
                (kind, origin, destination, price),
            )
            route_id = cursor.lastrowid
            await db.commit()
        audit_log.info("Route %s opened by %s: %s %s -> %s fee=%s",
                       route_id, interaction.user.id, kind, origin, destination, price)
        embed = discord.Embed(
            title="🚌 Route Opened",
            description=f"**{origin}** → **{destination}** by {kind}",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Route ID", value=f"#{route_id}", inline=True)
        embed.add_field(name="Standard fare", value=f"🪙 **{price:,}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @transport_group.command(name="list", description="Active routes")
    @app_commands.describe(kind="Filter by mode")
    @app_commands.choices(kind=[app_commands.Choice(name=k, value=k)
                                for k in ("Bus", "Train", "Ferry", "Air")])
    async def transport_list(self, interaction: discord.Interaction, kind: str = None):
        query = ("SELECT route_id, transport_type, origin, destination, price "
                 "FROM transport_routes WHERE status = 'active'")
        params: tuple = ()
        if kind:
            query += " AND transport_type = ?"
            params = (kind,)
        query += " ORDER BY route_id LIMIT 15"
        async with await self.db.get_connection() as db:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
        embed = discord.Embed(title="🚌 Dravian Transport Network", color=COLOR_GOLD)
        if not rows:
            embed.description = "No routes running. Ministers open one with `/transport route`."
        for route_id, rkind, origin, destination, price in rows:
            embed.add_field(
                name=f"#{route_id} {origin} → {destination}",
                value=f"{rkind} · standard 🪙 {price:,} · first 🪙 {price * 2:,}",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @transport_group.command(name="book", description="Book a journey")
    @app_commands.describe(route_id="Route to travel", travel_class="Cabin class")
    @app_commands.choices(travel_class=[app_commands.Choice(name=f"{k} ({v}× fare)", value=k)
                                        for k, v in {"Standard": 1, "First": 2}.items()])
    async def transport_book(self, interaction: discord.Interaction, route_id: int,
                             travel_class: str = "Standard"):
        multiplier = {"Standard": 1, "First": 2}.get(travel_class, 1)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT transport_type, origin, destination, price, status "
                "FROM transport_routes WHERE route_id = ?", (route_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            await interaction.response.send_message(
                f"❌ No route #{route_id}.", ephemeral=True)
            return
        kind, origin, destination, price, status = row
        if status != "active":
            await interaction.response.send_message(
                "❌ That route is not running.", ephemeral=True)
            return
        fare = price * multiplier
        user_id = str(interaction.user.id)
        if await self.db.get_balance(user_id) < fare:
            await interaction.response.send_message(
                f"❌ The fare is 🪙 **{fare:,}** — you cannot afford it.", ephemeral=True)
            return
        await self.db.remove_balance(user_id, fare, "transport",
                                     f"{kind} {origin}->{destination}")
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO transport_bookings (user_id, route_id, class, booked_at, status) "
                "VALUES (?, ?, ?, ?, 'active')",
                (user_id, route_id, travel_class, datetime.now().isoformat()),
            )
            booking_id = cursor.lastrowid
            await db.commit()
        embed = discord.Embed(
            title="🎫 Journey Booked",
            description=f"**{origin}** → **{destination}** ({kind}, {travel_class})",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Booking", value=f"#{booking_id}", inline=True)
        embed.add_field(name="Fare paid", value=f"🪙 **{fare:,}**", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @transport_group.command(name="tickets", description="Your bookings")
    async def transport_tickets(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT b.booking_id, r.transport_type, r.origin, r.destination, "
                "b.class, b.booked_at, b.status FROM transport_bookings b "
                "JOIN transport_routes r ON r.route_id = b.route_id "
                "WHERE b.user_id = ? ORDER BY b.booking_id DESC LIMIT 10",
                (str(interaction.user.id),),
            ) as cursor:
                rows = await cursor.fetchall()
        embed = discord.Embed(title=f"🎫 {interaction.user.display_name}'s Tickets",
                              color=COLOR_GOLD)
        if not rows:
            embed.description = "No journeys booked. `/transport book` starts one."
        for booking_id, kind, origin, destination, travel_class, booked_at, status in rows:
            embed.add_field(
                name=f"#{booking_id} {origin} → {destination}",
                value=f"{kind} · {travel_class} · **{status}** · {stamp(booked_at)}",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------- utilities (Part 24)
    PLANT_TYPES = {
        "Coal": (8000, 100),
        "Hydro": (12000, 150),
        "Solar": (10000, 80),
        "Nuclear": (20000, 200),
    }

    @utility_group.command(name="power", description="Build a power plant")
    @app_commands.describe(plant_type="Generation technology", location="Where it stands")
    @app_commands.choices(plant_type=[app_commands.Choice(
        name=f"{k} ({v[0]:,} Ovi · {v[1]} MW)", value=k)
        for k, v in {"Coal": (8000, 100), "Hydro": (12000, 150),
                     "Solar": (10000, 80), "Nuclear": (20000, 200)}.items()])
    async def utility_power(self, interaction: discord.Interaction, plant_type: str,
                            location: str):
        if plant_type not in self.PLANT_TYPES:
            await interaction.response.send_message(
                f"❌ Unknown technology **{plant_type}**.", ephemeral=True)
            return
        location = " ".join(location.split())[:40]
        if not location:
            await interaction.response.send_message(
                "❌ The plant needs a location.", ephemeral=True)
            return
        cost, output = self.PLANT_TYPES[plant_type]
        user_id = str(interaction.user.id)
        if await self.db.get_balance(user_id) < cost:
            await interaction.response.send_message(
                f"❌ A **{plant_type}** plant costs 🪙 **{cost:,}** — you cannot afford it.",
                ephemeral=True)
            return
        await self.db.remove_balance(user_id, cost, "utility", f"Power plant: {plant_type}")
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO energy_plants (owner_id, plant_type, output, location, built_at) "
                "VALUES (?, ?, ?, ?, date('now'))",
                (user_id, plant_type, output, location),
            )
            plant_id = cursor.lastrowid
            await db.commit()
        embed = discord.Embed(
            title="⚡ Grid Expanded",
            description=f"A **{plant_type}** plant now stands at {location}.",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Plant ID", value=f"#{plant_id}", inline=True)
        embed.add_field(name="Output", value=f"{output} MW", inline=True)
        embed.add_field(name="Cost", value=f"🪙 **{cost:,}**", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @utility_group.command(name="telecom", description="Raise a telecom tower")
    @app_commands.describe(location="Where it stands", coverage="Reach, 1-50 (150 Ovi each)")
    async def utility_telecom(self, interaction: discord.Interaction, location: str,
                              coverage: int = 10):
        location = " ".join(location.split())[:40]
        if not location:
            await interaction.response.send_message(
                "❌ The tower needs a location.", ephemeral=True)
            return
        if coverage < 1 or coverage > 50:
            await interaction.response.send_message(
                "❌ Coverage runs from 1 to 50.", ephemeral=True)
            return
        cost = coverage * 150
        user_id = str(interaction.user.id)
        if await self.db.get_balance(user_id) < cost:
            await interaction.response.send_message(
                f"❌ {coverage} coverage costs 🪙 **{cost:,}** — you cannot afford it.",
                ephemeral=True)
            return
        await self.db.remove_balance(user_id, cost, "utility", f"Telecom tower: {location}")
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO telecom_towers (location, coverage, built_at) VALUES (?, ?, date('now'))",
                (location, coverage),
            )
            tower_id = cursor.lastrowid
            await db.commit()
        embed = discord.Embed(
            title="📡 Signal Raised",
            description=f"A tower at {location} covers **{coverage}** districts.",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Tower ID", value=f"#{tower_id}", inline=True)
        embed.add_field(name="Cost", value=f"🪙 **{cost:,}**", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @utility_group.command(name="plants", description="Power plants on the grid")
    async def utility_plants(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT plant_id, owner_id, plant_type, output, location, built_at "
                "FROM energy_plants ORDER BY plant_id LIMIT 15"
            ) as cursor:
                rows = await cursor.fetchall()
        embed = discord.Embed(title="⚡ Generating Stations", color=COLOR_GOLD)
        if not rows:
            embed.description = "No plants built. `/utility power` breaks ground."
        for plant_id, owner_id, plant_type, output, location, built_at in rows:
            embed.add_field(
                name=f"#{plant_id} {plant_type} — {location}",
                value=f"{output} MW · <@{owner_id}> · {stamp(built_at)}",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @utility_group.command(name="towers", description="Telecom towers on the map")
    async def utility_towers(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT tower_id, location, coverage, built_at FROM telecom_towers "
                "ORDER BY tower_id LIMIT 15"
            ) as cursor:
                rows = await cursor.fetchall()
        embed = discord.Embed(title="📡 Telecom Towers", color=COLOR_GOLD)
        if not rows:
            embed.description = "No towers raised. `/utility telecom` starts the network."
        total = 0
        for tower_id, location, coverage, built_at in rows:
            total += coverage
            embed.add_field(name=f"#{tower_id} {location}",
                            value=f"coverage {coverage} · {stamp(built_at)}")
        embed.set_footer(text=f"Total coverage: {total}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Business(bot))
