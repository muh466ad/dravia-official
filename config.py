"""Dravia State Bot - Configuration"""
import os
from dotenv import load_dotenv

load_dotenv()

# Bot Configuration
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN not set in .env file")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0")) if os.getenv("DEV_GUILD_ID") else None

# Database
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Economy Settings
STARTING_BALANCE = 500
DAILY_UBI_AMOUNT = 50
WEEKLY_UBI_AMOUNT = 350

# Tax Rates (from Dravian law)
TAX_RATE_0_500 = 0.00      # 0-500 Ovi: 0%
TAX_RATE_501_2000 = 0.03   # 501-2000 Ovi: 3%
TAX_RATE_2001_5000 = 0.05  # 2001-5000 Ovi: 5%
TAX_RATE_5000_PLUS = 0.10  # Above 5000 Ovi: 10%

# Dravian Flag Colors
COLOR_CRIMSON = 0x8B0000
COLOR_GOLD = 0xD4AF37
COLOR_BLACK = 0x1A1A1A
COLOR_ACCENT = 0x4FC3F7  # Cyan accent for embeds