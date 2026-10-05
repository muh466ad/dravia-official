"""Dravia State Bot - Stock Market (Chrysanthemum Securities)"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os
import aiosqlite
import random

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Stock listings
STOCKS = {
    "DRVC": {"name": "Dravia Corp", "price": 100, "volatility": 0.10},
    "BANK": {"name": "Dravian Head Bank", "price": 250, "volatility": 0.05},
    "MINE": {"name": "Dravia Mining Co", "price": 80, "volatility": 0.15},
    "FARM": {"name": "Dravia Agriculture", "price": 50, "volatility": 0.08},
    "TECH": {"name": "Dravia Tech Solutions", "price": 150, "volatility": 0.20},
    "ENER": {"name": "Dravia Energy", "price": 120, "volatility": 0.12},
    "SHIP": {"name": "Dravia Shipping", "price": 90, "volatility": 0.10},
    "FOOD": {"name": "Dravia Foods", "price": 60, "volatility": 0.06}
}

class StockMarket(commands.Cog):
    """Stock market commands for Dravia."""
    
    stock_group = app_commands.Group(name="stock", description="Chrysanthemum Securities Exchange")
    
    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)
        self._update_prices()
    
    def _update_prices(self):
        """Simulate price movement."""
        for symbol, stock in STOCKS.items():
            change = random.uniform(-stock["volatility"], stock["volatility"])
            stock["price"] = max(10, int(stock["price"] * (1 + change)))
    
    @stock_group.command(name="list", description="View stock market")
    async def stocks(self, interaction: discord.Interaction):
        """View all stocks."""
        self._update_prices()
        
        embed = discord.Embed(
            title="📈 Chrysanthemum Securities Exchange",
            description="Dravia's official stock exchange",
            color=COLOR_GOLD
        )
        
        for symbol, stock in STOCKS.items():
            embed.add_field(
                name=f"{symbol} - {stock['name']}",
                value=f"💵 **{stock['price']}** Ovi\nVolatility: {stock['volatility']*100:.0f}%",
                inline=True
            )
        
        embed.set_footer(text="Use /stock buy to purchase shares")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @stock_group.command(name="buy", description="Buy stocks")
    @app_commands.describe(
        symbol="Stock symbol",
        shares="Number of shares"
    )
    async def buy_stock(self, interaction: discord.Interaction, symbol: str, shares: int):
        """Buy stocks."""
        user_id = str(interaction.user.id)
        
        if symbol.upper() not in STOCKS:
            await interaction.response.send_message(
                f"❌ Invalid stock. Available: {', '.join(STOCKS.keys())}",
                ephemeral=True
            )
            return
        
        if shares <= 0:
            await interaction.response.send_message("❌ Shares must be positive.", ephemeral=True)
            return
        
        stock = STOCKS[symbol.upper()]
        cost = stock["price"] * shares
        
        balance = await self.db.get_balance(user_id)
        if balance < cost:
            await interaction.response.send_message(
                f"❌ Insufficient funds. Need {cost:,} Ovi, you have {balance:,}.",
                ephemeral=True
            )
            return
        
        # Deduct and add to portfolio
        await self.db.remove_balance(user_id, cost, "stock_buy", f"Bought {shares} {symbol}")
        
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT shares FROM portfolio WHERE user_id = ? AND symbol = ?",
                (user_id, symbol.upper())
            ) as cursor:
                existing = await cursor.fetchone()
            
            if existing:
                await db.execute(
                    "UPDATE portfolio SET shares = shares + ? WHERE user_id = ? AND symbol = ?",
                    (shares, user_id, symbol.upper())
                )
            else:
                await db.execute(
                    "INSERT INTO portfolio (user_id, symbol, shares, avg_price) VALUES (?, ?, ?, ?)",
                    (user_id, symbol.upper(), shares, stock["price"])
                )
            
            await db.commit()
        
        embed = discord.Embed(
            title="✅ Purchase Complete",
            description=f"Bought **{shares}** shares of **{stock['name']}**",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Total Cost", value=f"🪙 **{cost:,}**", inline=True)
        embed.add_field(name="Price/Share", value=f"🪙 **{stock['price']}**", inline=True)
        embed.set_footer(text="Chrysanthemum Securities")
        
        await interaction.response.send_message(embed=embed)
    
    @stock_group.command(name="sell", description="Sell stocks")
    @app_commands.describe(
        symbol="Stock symbol",
        shares="Number of shares to sell"
    )
    async def sell_stock(self, interaction: discord.Interaction, symbol: str, shares: int):
        """Sell stocks."""
        user_id = str(interaction.user.id)
        
        if symbol.upper() not in STOCKS:
            await interaction.response.send_message("❌ Invalid stock.", ephemeral=True)
            return
        
        if shares <= 0:
            await interaction.response.send_message("❌ Shares must be positive.", ephemeral=True)
            return
        
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT shares FROM portfolio WHERE user_id = ? AND symbol = ?",
                (user_id, symbol.upper())
            ) as cursor:
                existing = await cursor.fetchone()
        
        if not existing or existing["shares"] < shares:
            await interaction.response.send_message(
                "❌ You don't have that many shares.",
                ephemeral=True
            )
            return
        
        stock = STOCKS[symbol.upper()]
        proceeds = stock["price"] * shares
        
        # Remove shares and add balance
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE portfolio SET shares = shares - ? WHERE user_id = ? AND symbol = ?",
                (shares, user_id, symbol.upper())
            )
            await db.execute(
                "DELETE FROM portfolio WHERE shares <= 0"
            )
            await db.commit()
        
        await self.db.add_balance(user_id, proceeds, "stock_sell", f"Sold {shares} {symbol}")
        
        embed = discord.Embed(
            title="✅ Sale Complete",
            description=f"Sold **{shares}** shares of **{stock['name']}**",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Proceeds", value=f"🪙 **{proceeds:,}**", inline=True)
        embed.add_field(name="Price/Share", value=f"🪙 **{stock['price']}**", inline=True)
        embed.set_footer(text="Chrysanthemum Securities")
        
        await interaction.response.send_message(embed=embed)
    
    @stock_group.command(name="portfolio", description="View your stock portfolio")
    async def portfolio(self, interaction: discord.Interaction):
        """View portfolio."""
        user_id = str(interaction.user.id)
        
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT symbol, shares, avg_price FROM portfolio WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                holdings = await cursor.fetchall()
        
        if not holdings:
            embed = discord.Embed(
                title="📊 Your Portfolio",
                description="You don't own any stocks yet.",
                color=COLOR_ACCENT
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        total_value = 0
        embed = discord.Embed(
            title="📊 Your Portfolio",
            color=COLOR_GOLD
        )
        
        for h in holdings:
            symbol = h["symbol"]
            shares = h["shares"]
            current_price = STOCKS.get(symbol, {}).get("price", 0)
            value = shares * current_price
            total_value += value
            
            embed.add_field(
                name=f"{symbol} - {STOCKS.get(symbol, {}).get('name', 'Unknown')}",
                value=f"Shares: **{shares}**\nValue: 🪙 **{value:,}**",
                inline=True
            )
        
        embed.add_field(name="Total Value", value=f"🪙 **{total_value:,}**", inline=False)
        embed.set_footer(text="Chrysanthemum Securities")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(StockMarket(bot))