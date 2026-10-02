"""Dravia State Bot - Lore & Characters"""
import discord
from discord import app_commands
from discord.ext import commands

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON

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
    "• The **Chrysanthemum Securities Exchange** opened the markets to every citizen."
)

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
