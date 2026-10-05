"""Dravia State Bot - Banking System"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import os
import asyncio
import aiosqlite

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from database import Database

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Interest rates from Dravian banking law
INTEREST_RATE_SAVINGS = 0.04  # 4% annual
INTEREST_RATE_LOAN = 0.15     # 15% annual
LOAN_TERMS = {
    "small": {"max": 10000, "weeks": 12},
    "medium": {"max": 50000, "weeks": 26},
    "large": {"max": 200000, "weeks": 52}
}

class Banking(commands.Cog):
    """Banking commands for Dravia."""
    
    bank_group = app_commands.Group(name="bank", description="Dravian Head Bank")
    
    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)
    
    async def get_bank_account(self, user_id: str) -> dict:
        """Get or create user's bank account."""
        async with await self.db.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM bank_accounts WHERE user_id = ?", (user_id,)
            ) as cursor:
                account = await cursor.fetchone()
            
            if not account:
                await db.execute(
                    "INSERT INTO bank_accounts (user_id, savings, loan_balance, loan_term, loan_start) VALUES (?, ?, ?, ?, ?)",
                    (user_id, 0, 0, 0, None)
                )
                await db.commit()
                
                async with db.execute(
                    "SELECT * FROM bank_accounts WHERE user_id = ?", (user_id,)
                ) as cursor:
                    account = await cursor.fetchone()
            
            return dict(account) if account else None
    
    @bank_group.command(name="balance", description="View your bank account")
    async def bank(self, interaction: discord.Interaction):
        """View bank account."""
        user_id = str(interaction.user.id)
        account = await self.get_bank_account(user_id)
        
        # Calculate interest earned (simplified)
        annual_yield = account["savings"] * INTEREST_RATE_SAVINGS
        weekly_yield = annual_yield / 52
        
        # Loan info
        loan_info = ""
        if account["loan_balance"] > 0:
            weeks_remaining = account["loan_term"] - ((datetime.now() - datetime.fromisoformat(account["loan_start"])).days // 7)
            loan_info = f"\n📋 **Loan:** 🪙 {account['loan_balance']:,} ({weeks_remaining} weeks remaining)"
        else:
            loan_info = "\n📋 **Loan:** None — apply with `/bank loan`"
        
        embed = discord.Embed(
            title="🏦 Dravian Head Bank",
            description=f"{interaction.user.display_name}'s Account",
            color=COLOR_GOLD
        )
        embed.add_field(name="💰 Savings", value=f"🪙 **{account['savings']:,}**", inline=True)
        embed.add_field(name="📈 Annual Interest", value=f"**{INTEREST_RATE_SAVINGS*100}%**", inline=True)
        embed.add_field(name="📊 Weekly Yield", value=f"~🪙 **{weekly_yield:.0f}**", inline=True)
        embed.add_field(name="🏧 Loan Balance", value=f"🪙 **{account['loan_balance']:,}**", inline=True)
        embed.set_footer(text="Dravian Head Bank | Deposits insured up to 10,000 Ovi per depositor")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @bank_group.command(name="deposit", description="Deposit Ovi to your bank account")
    @app_commands.describe(amount="Amount to deposit")
    async def deposit(self, interaction: discord.Interaction, amount: int):
        """Deposit money to bank."""
        user_id = str(interaction.user.id)
        
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        
        # Check user has the money
        balance = await self.db.get_balance(user_id)
        if balance < amount:
            await interaction.response.send_message(
                f"❌ Insufficient funds. You have {balance:,} Ovi.",
                ephemeral=True
            )
            return
        
        # Get account
        account = await self.get_bank_account(user_id)
        
        # Transfer
        await self.db.remove_balance(user_id, amount, "bank_deposit", "Deposit to bank")
        
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE bank_accounts SET savings = savings + ? WHERE user_id = ?",
                (amount, user_id)
            )
            await db.commit()
        
        new_savings = account["savings"] + amount
        
        embed = discord.Embed(
            title="✅ Deposit Successful",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Amount Deposited", value=f"🪙 **{amount:,}**", inline=True)
        embed.add_field(name="New Savings", value=f"🪙 **{new_savings:,}**", inline=True)
        embed.set_footer(text="Dravian Head Bank")
        
        await interaction.response.send_message(embed=embed)
    
    @bank_group.command(name="withdraw", description="Withdraw Ovi from your bank")
    @app_commands.describe(amount="Amount to withdraw")
    async def withdraw(self, interaction: discord.Interaction, amount: int):
        """Withdraw money from bank."""
        user_id = str(interaction.user.id)
        
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        
        account = await self.get_bank_account(user_id)
        
        if account["savings"] < amount:
            await interaction.response.send_message(
                f"❌ Insufficient savings. You have {account['savings']:,} Ovi in the bank.",
                ephemeral=True
            )
            return
        
        # Transfer
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE bank_accounts SET savings = savings - ? WHERE user_id = ?",
                (amount, user_id)
            )
            await db.commit()
        
        await self.db.add_balance(user_id, amount, "bank_withdrawal", "Withdrawal from bank")
        
        embed = discord.Embed(
            title="✅ Withdrawal Successful",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Amount Withdrawn", value=f"🪙 **{amount:,}**", inline=True)
        embed.add_field(name="Remaining Savings", value=f"🪙 **{account['savings'] - amount:,}**", inline=True)
        embed.set_footer(text="Dravian Head Bank")
        
        await interaction.response.send_message(embed=embed)
    
    @bank_group.command(name="loan", description="Apply for a bank loan")
    @app_commands.describe(
        size="Loan size",
        amount="Amount to borrow"
    )
    @app_commands.choices(size=[
        app_commands.Choice(name="Small (up to 10,000 Ovi, 12 weeks)", value="small"),
        app_commands.Choice(name="Medium (up to 50,000 Ovi, 26 weeks)", value="medium"),
        app_commands.Choice(name="Large (up to 200,000 Ovi, 52 weeks)", value="large")
    ])
    async def apply_loan(self, interaction: discord.Interaction, size: str, amount: int):
        """Apply for a loan."""
        user_id = str(interaction.user.id)
        account = await self.get_bank_account(user_id)
        
        # Check terms
        terms = LOAN_TERMS[size]
        if amount > terms["max"]:
            await interaction.response.send_message(
                f"❌ Maximum {size} loan is {terms['max']:,} Ovi.",
                ephemeral=True
            )
            return
        
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        
        # Check existing loan
        if account["loan_balance"] > 0:
            await interaction.response.send_message(
                "❌ You already have an active loan. Pay it off first.",
                ephemeral=True
            )
            return
        
        # Check minimum savings requirement (10% of loan)
        min_savings = amount * 0.10
        if account["savings"] < min_savings:
            await interaction.response.send_message(
                f"❌ You need at least {min_savings:,} Ovi in savings (10% down payment) to get a loan.",
                ephemeral=True
            )
            return
        
        # Calculate interest
        interest = amount * INTEREST_RATE_LOAN
        total_due = amount + interest
        weekly_payment = total_due / terms["weeks"]
        
        # Grant loan
        async with await self.db.get_connection() as db:
            await db.execute(
                "UPDATE bank_accounts SET loan_balance = ?, loan_term = ?, loan_start = ? WHERE user_id = ?",
                (total_due, terms["weeks"], datetime.now().isoformat(), user_id)
            )
            await db.commit()
        
        await self.db.add_balance(user_id, amount, "loan", f"{size} loan approved")
        
        embed = discord.Embed(
            title="✅ Loan Approved!",
            description=f"**{size.title()} Loan** granted",
            color=COLOR_ACCENT
        )
        embed.add_field(name="Principal", value=f"🪙 **{amount:,}**", inline=True)
        embed.add_field(name="Interest (15%)", value=f"🪙 **{interest:.0f}**", inline=True)
        embed.add_field(name="Total Due", value=f"🪙 **{total_due:.0f}**", inline=True)
        embed.add_field(name="Term", value=f"**{terms['weeks']} weeks**", inline=True)
        embed.add_field(name="Weekly Payment", value=f"~🪙 **{weekly_payment:.0f}**", inline=True)
        embed.set_footer(text="Dravian Head Bank | Default = seizure of assets")
        
        await interaction.response.send_message(embed=embed)
    
    @bank_group.command(name="repay", description="Make a loan payment")
    @app_commands.describe(amount="Payment amount (leave empty for weekly minimum)")
    async def pay_loan(self, interaction: discord.Interaction, amount: int = None):
        """Pay towards loan."""
        user_id = str(interaction.user.id)
        account = await self.get_bank_account(user_id)
        
        if account["loan_balance"] <= 0:
            await interaction.response.send_message("❌ You have no active loan.", ephemeral=True)
            return
        
        # Calculate weekly minimum
        weeks_passed = (datetime.now() - datetime.fromisoformat(account["loan_start"])).days // 7
        weeks_remaining = max(0, account["loan_term"] - weeks_passed)
        weekly_min = account["loan_balance"] / max(1, weeks_remaining)
        
        # Use weekly min if not specified
        if amount is None:
            amount = int(weekly_min)
        
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        
        # Check funds
        balance = await self.db.get_balance(user_id)
        if balance < amount:
            await interaction.response.send_message(
                f"❌ Insufficient funds. You have {balance:,} Ovi.",
                ephemeral=True
            )
            return
        
        # Process payment
        await self.db.remove_balance(user_id, amount, "loan_payment", "Loan payment")
        
        new_balance = max(0, account["loan_balance"] - amount)
        
        async with await self.db.get_connection() as db:
            if new_balance <= 0:
                await db.execute(
                    "UPDATE bank_accounts SET loan_balance = 0, loan_term = 0, loan_start = NULL WHERE user_id = ?",
                    (user_id,)
                )
                message = "🎉 **Loan Fully Paid Off!** Congratulations!"
            else:
                await db.execute(
                    "UPDATE bank_accounts SET loan_balance = ? WHERE user_id = ?",
                    (new_balance, user_id)
                )
                message = "✅ Payment applied"
            
            await db.commit()
        
        embed = discord.Embed(
            title=message,
            color=COLOR_ACCENT if new_balance > 0 else COLOR_GOLD
        )
        embed.add_field(name="Payment", value=f"🪙 **{amount:,}**", inline=True)
        embed.add_field(name="Remaining", value=f"🪙 **{new_balance:,}**", inline=True)
        embed.set_footer(text="Dravian Head Bank")
        
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Banking(bot))