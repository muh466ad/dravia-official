"""Dravia State Bot - Media (Dravian Press & Broadcasting)

Tables: `media_outlets`, `comics`. Media Owners found outlets and pass them
on; anyone may publish a comic series, with issue numbers allocated by the
register. Dates render through `stamp()`.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, ovi, success, warning
from utils.checks import requires_media_owner
from utils.validation import text

#: media_type -> one-off licence fee.
MEDIA_TYPES = {
    "Newspaper": 2000,
    "Radio": 3000,
    "Television": 5000,
    "Magazine": 1500,
}

COMIC_LIMIT = 800

_OUTLET_COLS = ("outlet_id", "name", "media_type", "owner_id",
                "license_fee", "created_at")


class Media(DraviaCog):
    """Press & Broadcasting commands."""

    group_name = "economy"
    media_group = app_commands.Group(name="media", description="Outlets and publishing")

    # ------------------------------------------------------------ helpers
    async def _get_outlet(self, outlet_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM media_outlets WHERE outlet_id = ?", (outlet_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_OUTLET_COLS, row)) if row else None

    # ------------------------------------------------------------ commands
    @media_group.command(name="found", description="Found an outlet (Media Owner)")
    @app_commands.describe(name="Outlet name", media_type="Format")
    @app_commands.choices(media_type=[app_commands.Choice(name=f"{k} ({v:,} Ovi)", value=k)
                                       for k, v in MEDIA_TYPES.items()])
    @handles_validation
    @requires_media_owner
    async def media_found(self, interaction: discord.Interaction, name: str,
                          media_type: str = "Newspaper"):
        name = text(name, field="Name", maximum=60)
        media_type = media_type if media_type in MEDIA_TYPES else "Newspaper"
        fee = MEDIA_TYPES[media_type]
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT 1 FROM media_outlets WHERE name = ? COLLATE NOCASE", (name,)
            ) as cur:
                if await cur.fetchone():
                    await self.fail(interaction, f"**{name}** is already on air.")
                    return
            if not await self.debit(user_id, fee, "media", f"Licence: {name}"):
                await self.fail(interaction,
                                f"The {media_type} licence costs {ovi(fee)} — you cannot afford it.")
                return
            await db.execute(
                "INSERT INTO media_outlets (name, media_type, owner_id, license_fee, created_at) "
                "VALUES (?, ?, ?, ?, date('now'))",
                (name, media_type, user_id, fee),
            )
            await db.commit()
            async with db.execute("SELECT MAX(outlet_id) FROM media_outlets") as cur:
                outlet_id = (await cur.fetchone())[0]
        log_action("media", "found", user_id, outlet=outlet_id, name=name, media_type=media_type)
        embed = success("Licence granted", f"**{name}** ({media_type}) may begin publishing.")
        embed.add_field(name="Outlet ID", value=f"#{outlet_id}")
        embed.add_field(name="Licence fee", value=ovi(fee))
        embed.add_field(name="Owner", value=f"<@{user_id}>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @media_group.command(name="outlets", description="Licensed outlets")
    async def media_outlets(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT outlet_id, name, media_type, owner_id FROM media_outlets "
                "ORDER BY outlet_id LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="📺 Licensed Media", color=COLOR_GOLD)
        if not rows:
            embed.description = "No outlets licensed. Media Owners use `/media found`."
        for outlet_id, name, media_type, owner_id in rows:
            embed.add_field(name=f"#{outlet_id} {name}",
                            value=f"{media_type} · owned by <@{owner_id}>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @media_group.command(name="info", description="Read one outlet")
    @app_commands.describe(outlet_id="Outlet to inspect")
    async def media_info(self, interaction: discord.Interaction, outlet_id: int):
        outlet = await self._get_outlet(outlet_id)
        if outlet is None:
            await self.fail(interaction, f"No outlet #{outlet_id} exists.")
            return
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM comics WHERE title LIKE ?",
                (f"%{outlet['name']}%",),
            ) as cur:
                related = (await cur.fetchone())[0]
        embed = DraviaEmbed(title=f"📺 {outlet['name']}", color=COLOR_GOLD)
        embed.add_field(name="Format", value=outlet["media_type"], inline=True)
        embed.add_field(name="Owner", value=f"<@{outlet['owner_id']}>", inline=True)
        embed.add_field(name="Licence fee", value=ovi(outlet["license_fee"]), inline=True)
        embed.add_field(name="Licensed",
                        value=stamp(outlet["created_at"]), inline=True)
        embed.add_field(name="Comic series matching name", value=str(related), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @media_group.command(name="transfer", description="Sell an outlet to another citizen")
    @app_commands.describe(outlet_id="Outlet to pass on", new_owner="Who receives it")
    async def media_transfer(self, interaction: discord.Interaction, outlet_id: int,
                             new_owner: discord.Member):
        outlet = await self._get_outlet(outlet_id)
        if outlet is None:
            await self.fail(interaction, f"No outlet #{outlet_id} exists.")
            return
        if outlet["owner_id"] != str(interaction.user.id):
            await self.fail(interaction, "Only the owner may transfer an outlet.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE media_outlets SET owner_id = ? WHERE outlet_id = ?",
                             (str(new_owner.id), outlet_id))
            await db.commit()
        log_action("media", "transfer", str(interaction.user.id),
                   outlet=outlet_id, to=str(new_owner.id))
        embed = success("Ownership transferred",
                        f"**{outlet['name']}** now belongs to **{new_owner.display_name}**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @media_group.command(name="comic", description="Publish the next issue of a series")
    @app_commands.describe(title="Series title", content="The strip")
    @handles_validation
    async def media_comic(self, interaction: discord.Interaction, title: str, content: str):
        title = text(title, field="Title", maximum=80)
        content = text(content, field="Strip", maximum=COMIC_LIMIT)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COALESCE(MAX(issue_number), 0) + 1 FROM comics WHERE title = ?",
                (title,),
            ) as cur:
                issue = (await cur.fetchone())[0]
            await db.execute(
                "INSERT INTO comics (title, issue_number, content, published_at) "
                "VALUES (?, ?, ?, date('now'))",
                (title, issue, content),
            )
            await db.commit()
            async with db.execute(
                "SELECT comic_id FROM comics WHERE title = ? AND issue_number = ?",
                (title, issue),
            ) as cur:
                comic_id = (await cur.fetchone())[0]
        log_action("media", "comic", str(interaction.user.id),
                   comic=comic_id, title=title, issue=issue)
        embed = success("Published", f"**{title}** #{issue} is out.")
        embed.add_field(name="Comic ID", value=f"#{comic_id}")
        embed.set_footer(text="Read it back with /media read")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @media_group.command(name="comics", description="Series in print")
    @app_commands.describe(title="Filter to one series")
    async def media_comics(self, interaction: discord.Interaction, title: str = None):
        query = ("SELECT title, MAX(issue_number), COUNT(*), MAX(published_at) "
                 "FROM comics")
        params: tuple = ()
        if title:
            query += " WHERE title LIKE ?"
            params = (f"%{title}%",)
        query += " GROUP BY title ORDER BY MAX(published_at) DESC LIMIT 10"
        async with await self.db.get_connection() as db:
            async with db.execute(query, params) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="📚 Comics in Print", color=COLOR_GOLD)
        if not rows:
            embed.description = "Nothing in print yet. `/media comic` starts a series."
        for series, latest, count, published_at in rows:
            embed.add_field(name=series,
                            value=f"#{count} issue(s) · latest #{latest} · "
                                  f"{stamp(published_at) if published_at else '—'}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @media_group.command(name="read", description="Read an issue")
    @app_commands.describe(comic_id="Issue to read")
    async def media_read(self, interaction: discord.Interaction, comic_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT title, issue_number, content, published_at FROM comics "
                "WHERE comic_id = ?", (comic_id,)
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            await self.fail(interaction, f"No issue #{comic_id} exists.")
            return
        title, issue, content, published_at = row
        embed = DraviaEmbed(title=f"📚 {title} #{issue}", color=COLOR_GOLD)
        embed.description = content
        embed.set_footer(text=f"Published {stamp(published_at)}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Media(bot))
