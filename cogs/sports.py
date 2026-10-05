"""Dravia State Bot - Sports (Dravian Athletic Union)

Tables: `sports_teams`, `sports_matches`. Captains found teams, challenge
each other, and the Tournament Organiser records results. Fixtures and
standings render through `stamp()`.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, ovi, success, warning
from utils.checks import requires_tournament_organiser
from utils.validation import dravian_date as parse_date
from utils.validation import text

SPORTS = ["Football", "Basketball", "Athletics", "Cycling", "Boxing"]

#: Entry fee to found a team.
ENTRY_FEE = 500

_TEAM_COLS = ("team_id", "name", "sport", "captain_id", "created_at")


class Sports(DraviaCog):
    """Athletic Union commands."""

    group_name = "economy"
    sports_group = app_commands.Group(name="sports", description="Teams, fixtures and results")

    # ------------------------------------------------------------ helpers
    async def _get_team(self, team_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT * FROM sports_teams WHERE team_id = ?", (team_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(zip(_TEAM_COLS, row)) if row else None

    def _is_captain(self, interaction, team) -> bool:
        return team and team["captain_id"] == str(interaction.user.id)

    # ------------------------------------------------------------ commands
    @sports_group.command(name="team", description="Found a team (500 Ovi entry)")
    @app_commands.describe(name="Team name", sport="Discipline")
    @app_commands.choices(sport=[app_commands.Choice(name=s, value=s) for s in SPORTS])
    @handles_validation
    async def sports_team(self, interaction: discord.Interaction, name: str,
                          sport: str = "Football"):
        name = text(name, field="Team name", maximum=60)
        sport = sport if sport in SPORTS else SPORTS[0]
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT 1 FROM sports_teams WHERE name = ? COLLATE NOCASE", (name,)
            ) as cur:
                if await cur.fetchone():
                    await self.fail(interaction, f"**{name}** already plays.")
                    return
            if not await self.debit(user_id, ENTRY_FEE, "sports", f"Founded {name}"):
                await self.fail(interaction,
                                f"Entry costs {ovi(ENTRY_FEE)} — you cannot afford it.")
                return
            await db.execute(
                "INSERT INTO sports_teams (name, sport, captain_id, created_at) "
                "VALUES (?, ?, ?, date('now'))",
                (name, sport, user_id),
            )
            await db.commit()
            async with db.execute("SELECT MAX(team_id) FROM sports_teams") as cur:
                team_id = (await cur.fetchone())[0]
        log_action("sports", "team", user_id, team=team_id, name=name, sport=sport)
        embed = success("Club registered", f"**{name}** enters the {sport} league.")
        embed.add_field(name="Team ID", value=f"#{team_id}")
        embed.add_field(name="Captain", value=f"<@{user_id}>")
        embed.add_field(name="Next", value="Issue a challenge with `/sports challenge`.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @sports_group.command(name="teams", description="Every registered club")
    async def sports_teams(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT team_id, name, sport, captain_id FROM sports_teams "
                "ORDER BY team_id LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
            async with db.execute(
                "SELECT winner_id, COUNT(*) FROM sports_matches "
                "WHERE winner_id IS NOT NULL GROUP BY winner_id"
            ) as cur:
                wins = dict(await cur.fetchall())
        embed = DraviaEmbed(title="🏟️ Dravian Clubs", color=COLOR_GOLD)
        if not rows:
            embed.description = "No clubs yet. `/sports team` registers the first."
        for team_id, name, sport, captain_id in rows:
            embed.add_field(name=f"#{team_id} {name}",
                            value=f"{sport} · captain <@{captain_id}> · "
                                  f"{wins.get(team_id, 0)} win(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @sports_group.command(name="info", description="Club record and honours")
    @app_commands.describe(team_id="Club to inspect")
    async def sports_info(self, interaction: discord.Interaction, team_id: int):
        team = await self._get_team(team_id)
        if team is None:
            await self.fail(interaction, f"No team #{team_id} exists.")
            return
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM sports_matches WHERE winner_id = ?", (team_id,)
            ) as cur:
                wins = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM sports_matches "
                "WHERE (team1_id = ? OR team2_id = ?) AND winner_id IS NULL",
                (team_id, team_id),
            ) as cur:
                upcoming = (await cur.fetchone())[0]
        embed = DraviaEmbed(title=f"🏟️ {team['name']}", color=COLOR_GOLD)
        embed.add_field(name="Sport", value=team["sport"], inline=True)
        embed.add_field(name="Captain", value=f"<@{team['captain_id']}>", inline=True)
        embed.add_field(name="Founded", value=stamp(team["created_at"]), inline=True)
        embed.add_field(name="Wins", value=str(wins), inline=True)
        embed.add_field(name="Fixtures pending", value=str(upcoming), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @sports_group.command(name="challenge", description="Schedule a match against another club")
    @app_commands.describe(team1_id="Your club", team2_id="Opponent",
                           match_date="Kick-off (DD/MM/YYYY)")
    @handles_validation
    async def sports_challenge(self, interaction: discord.Interaction, team1_id: int,
                               team2_id: int, match_date: str):
        team1 = await self._get_team(team1_id)
        team2 = await self._get_team(team2_id)
        if team1 is None or team2 is None:
            await self.fail(interaction, "Both teams must exist (check `/sports teams`).")
            return
        if team1_id == team2_id:
            await self.fail(interaction, "A club cannot play itself.")
            return
        if not self._is_captain(interaction, team1):
            await self.fail(interaction, f"Only the captain of **{team1['name']}** may challenge.")
            return
        when = parse_date(match_date, field="Match date", future_okay=True)
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO sports_matches (team1_id, team2_id, scheduled_at) VALUES (?, ?, ?)",
                (team1_id, team2_id, f"{when.isoformat()} 18:00"),
            )
            await db.commit()
            async with db.execute("SELECT MAX(match_id) FROM sports_matches") as cur:
                match_id = (await cur.fetchone())[0]
        log_action("sports", "challenge", str(interaction.user.id),
                   match=match_id, home=team1_id, away=team2_id)
        embed = success("Fixture scheduled",
                        f"**{team1['name']}** vs **{team2['name']}** — {stamp(when.isoformat())}.")
        embed.add_field(name="Match ID", value=f"#{match_id}")
        embed.set_footer(text="The Organiser records the result with /sports result")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @sports_group.command(name="result", description="Record a result (Tournament Organiser)")
    @app_commands.describe(match_id="Fixture to settle", winner_team_id="Who won")
    @requires_tournament_organiser
    async def sports_result(self, interaction: discord.Interaction, match_id: int,
                            winner_team_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT team1_id, team2_id, winner_id FROM sports_matches WHERE match_id = ?",
                (match_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                await self.fail(interaction, f"No match #{match_id} exists.")
                return
            team1_id, team2_id, winner_id = row
            if winner_id is not None:
                await self.fail(interaction, f"Match #{match_id} already has a result.")
                return
            if winner_team_id not in (team1_id, team2_id):
                await self.fail(interaction,
                                f"Team #{winner_team_id} does not play in match #{match_id}.")
                return
            cur = await db.execute(
                "UPDATE sports_matches SET winner_id = ? WHERE match_id = ? "
                "AND winner_id IS NULL",
                (winner_team_id, match_id),
            )
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"Match #{match_id} was just recorded by someone else.")
            return
        team = await self._get_team(winner_team_id)
        log_action("sports", "result", str(interaction.user.id),
                   match=match_id, winner=winner_team_id)
        embed = success("Result recorded", f"**{team['name']}** wins match #{match_id}!")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @sports_group.command(name="fixtures", description="Upcoming matches")
    async def sports_fixtures(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT m.match_id, m.scheduled_at, t1.name, t2.name "
                "FROM sports_matches m "
                "JOIN sports_teams t1 ON t1.team_id = m.team1_id "
                "JOIN sports_teams t2 ON t2.team_id = m.team2_id "
                "WHERE m.winner_id IS NULL ORDER BY m.scheduled_at LIMIT 10"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🏟️ Fixtures", color=COLOR_GOLD)
        if not rows:
            embed.description = "No matches scheduled. Captains use `/sports challenge`."
        for match_id, scheduled_at, home, away in rows:
            embed.add_field(name=f"#{match_id} {home} vs {away}",
                            value=stamp(scheduled_at))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @sports_group.command(name="standings", description="League table by wins")
    async def sports_standings(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT t.team_id, t.name, t.sport, COUNT(m.match_id) "
                "FROM sports_teams t "
                "LEFT JOIN sports_matches m ON m.winner_id = t.team_id "
                "GROUP BY t.team_id ORDER BY COUNT(m.match_id) DESC, t.team_id LIMIT 10"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🏟️ Standings", color=COLOR_GOLD)
        if not rows:
            embed.description = "No clubs to rank yet."
        for place, (team_id, name, sport, wins) in enumerate(rows, start=1):
            embed.add_field(name=f"{place}. {name}",
                            value=f"{sport} · {wins} win(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Sports(bot))
