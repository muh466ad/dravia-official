"""Dravia State Bot - Lore & Characters"""
import discord
from discord import app_commands
from discord.ext import commands

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON
from utils.calendar import CURRENT_YEAR, FOUNDED_YEAR, ERA

FLAG_DESCRIPTION = (
    "**Three vertical stripes:**\n"
    "🟥 **Deep crimson red** (left)\n"
    "⬛ **Wide black** (center)\n"
    "🟨 **Golden yellow** (right)\n\n"
    "In the centre of the black stripe: a **crimson swan with wings spread**, "
    "enclosed by a **golden laurel wreath**, with **six golden stars** above."
)

CHARACTERS = [
    ("Prince Nika GOLD", "Curial (Gen Dravia) — father of the Republic's institutions"),
    ("Zandros Zlerov", "Grand Minister (DPP) — statesman and orator"),
    ("Iulius Augustus", "Party leader (DPP) — master strategist"),
    ("Minion Bob", "Minister of Economy — architect of the Ovi"),
    ("Centurio Drav (Captain Drav)", "Hero of the De Quatta comic"),
    ("Sebastian Devoon", "Scientist of the De Quatta comic"),
]

HISTORY = (
    "**The Republic of Dravia** was founded on the principles of economic liberty, "
    "fair taxation and the rule of law.\n\n"
    "• The **Ovi (🪙)** was established as the national currency with a universal citizen's start of 500 Ovi.\n"
    "• The **Curia Draviae** was convened to legislate by open vote.\n"
    "• The **Cygnus Decree** created the great grant programmes for citizens, farmers and students.\n"
    "• The **De Custodia Publica Draviae** organised the police under independent oversight (IPOC).\n"
    "• The **Chrysanthemum Securities Exchange** opened the markets to every citizen.\n\n"
    f"*Use `/lore timeline` for the dated chronology from {FOUNDED_YEAR} to the present.*"
)

# Dated chronology of the Republic, oldest first. Years are editable in one
# place; FOUNDED_YEAR and CURRENT_YEAR (utils/calendar.py) frame the span.
# (year, title, description)
TIMELINE = [
    (1953, "Founding of the Republic",
     "Dravia is constituted as a republic on the principles of economic liberty, "
     "progressive taxation and the rule of law."),
    (1957, "The Ovi established",
     "The **Ovi (🪙)** becomes the national currency. Every citizen receives a "
     "universal start of **500 Ovi**."),
    (1959, "First session of the Curia Draviae",
     "The legislative chamber is convened to make law by open vote, seated for the "
     "first time in the Hall of Curiae."),
    (1962, "The Cygnus Decree",
     "The great grant programmes are created for citizens, farmers and students, "
     "administered by the Treasury."),
    (1966, "Universal Citizenship Act",
     "Citizenship is granted on residence alone. The Ministry of the Interior "
     "begins issuing Dravian Identity cards."),
    (1968, "De Custodia Publica Draviae",
     "The police are reorganised under **independent oversight (IPOC)**, ending "
     "the practice of internal police investigations."),
    (1971, "Free Press Act",
     "The *Dravian Daily* and the Government Gazette are placed beyond executive "
     "censorship. The Ministry of Information becomes the Ministry of Culture."),
    (1974, "Chrysanthemum Securities Exchange",
     "The markets open to every citizen. The **SEC** is created to police them."),
    (1978, "Progressive Tax Reform",
     "Taxation is restructured into progressive bands. The Revenue Staff are "
     "given enforcement powers of their own."),
    (1981, "De Quatta debuts",
     "**Centurio Drav** and **Sebastian Devoon** appear in the first strip of the "
     "national comic, published in the Gazette."),
    (1983, "Consumer Protection Authority",
     "The Authority is constituted to hear citizen complaints against traders, "
     "with power to order refunds and levy fines."),
    (1985, "Present Day",
     "The Republic in its current form: Curia legislating, the Gazette printing, "
     "and the Ovi in circulation."),
]

CONSTITUTION = (
    "**The Economic Constitution of Dravia**\n\n"
    "I. Every citizen has the right to **work, enterprise and property**.\n"
    "II. Taxation shall be **progressive, public and lawful**.\n"
    "III. The State may not seize property except by **due process of law**.\n"
    "IV. The **Curia** alone makes law; the executive enforces it.\n"
    "V. All public finances shall be **audited and published**.\n"
    "VI. Civil servants may **refuse unlawful orders** (Art. 36, Civil Service Act).\n"
    "VII. Whistleblowers shall be **protected**."
)


class Lore(commands.Cog):
    """Lore commands for Dravia."""

    lore_group = app_commands.Group(name="lore", description="Lore of the Republic of Dravia")
    
    def __init__(self, bot):
        self.bot = bot

    @lore_group.command(name="flag", description="Display the Dravian flag and its meaning")
    async def lore_flag(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏁 Flag of the Republic of Dravia",
            description=FLAG_DESCRIPTION,
            color=COLOR_CRIMSON,
        )
        embed.add_field(
            name="Symbolism",
            value="Crimson = courage & sacrifice | Black = resolve & industry | Gold = prosperity & honour",
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | Long live the Republic!")
        await interaction.response.send_message(embed=embed)

    @lore_group.command(name="characters", description="List all official characters")
    async def lore_characters(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🎭 Official Characters of Dravia", color=COLOR_GOLD)
        for name, role in CHARACTERS:
            embed.add_field(name=name, value=role, inline=False)
        embed.set_footer(text="Republic of Dravia | State Chronicle")
        await interaction.response.send_message(embed=embed)

    @lore_group.command(name="timeline", description="Dated chronology of the Republic")
    async def lore_timeline(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📜 Timeline of the Republic of Dravia",
            description=(
                f"*{FOUNDED_YEAR} — {CURRENT_YEAR} ({ERA})*"
            ),
            color=COLOR_CRIMSON,
        )
        for year, title, description in TIMELINE:
            marker = " ◀ present" if year == CURRENT_YEAR else ""
            embed.add_field(name=f"{year}{marker}", value=f"**{title}**\n{description}", inline=False)
        embed.set_footer(text="Republic of Dravia | State Chronicle")
        await interaction.response.send_message(embed=embed)

    @lore_group.command(name="history", description="View Dravian history")
    async def lore_history(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📖 History of Dravia", description=HISTORY, color=COLOR_ACCENT)
        embed.set_footer(text="Republic of Dravia | State Chronicle")
        await interaction.response.send_message(embed=embed)

    @lore_group.command(name="constitution", description="View the Economic Constitution")
    async def lore_constitution(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📜 The Economic Constitution", description=CONSTITUTION, color=COLOR_GOLD)
        embed.set_footer(text="Republic of Dravia | Curia Draviae")
        await interaction.response.send_message(embed=embed)

    @lore_group.command(name="comic", description="Info on the De Quatta comics")
    async def lore_comic(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="💥 De Quatta",
            description=(
                "The official comic of the Republic!\n\n"
                "**Centurio Drav (Captain Drav)** — hero of the people, defender of the frontier.\n"
                "**Sebastian Devoon** — brilliant scientist whose inventions power the State.\n\n"
                "New strips are published in the Government Gazette."
            ),
            color=COLOR_ACCENT,
        )
        embed.set_footer(text="Republic of Dravia | Information & Culture Ministry")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Lore(bot))
