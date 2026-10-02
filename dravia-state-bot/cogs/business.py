"""Dravia State Bot - Business System"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import os
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
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
        embed.add_field(name="Next Renewal", value=f"<t:{int((datetime.now() + timedelta(days=30)).timestamp())}:D>", inline=True)
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
        embed.add_field(name="Next Due", value=f"<t:{int((datetime.now() + timedelta(days=30)).timestamp())}:D>", inline=True)
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


async def setup(bot):
    await bot.add_cog(Business(bot))
