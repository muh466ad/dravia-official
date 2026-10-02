"""Dravia State Bot - Permission Checks

Role names come from the Permissions Matrix (Part 21 of the charter).
Roles are looked up by name so each guild can create them with any ID.
"""
import discord
from discord import app_commands

# Role names required for privileged command groups
ROLE_POLICE = "Police Officer"
ROLE_POLICE_SUPERVISOR = "Sergeant"
ROLE_BANK_STAFF = "Bank Staff"
ROLE_REVENUE = "Revenue Staff"
ROLE_SEC = "SEC"
ROLE_CONSUMER = "Consumer Protection"
ROLE_CURIAL = "Curial"
ROLE_MINISTER = "Minister"
ROLE_ADMIN = "Admin"
ROLE_JOURNALIST = "Journalist"
ROLE_CIVIL_SERVANT = "Civil Servant"
ROLE_CUSTOMS = "Customs Officer"


def has_role_by_name(member: discord.Member, role_name: str) -> bool:
    if member is None:
        return False
    if member.guild_permissions.administrator:
        return True
    return any(role.name.lower() == role_name.lower() for role in member.roles)


def role_check(role_name: str):
    """Return a check predicate requiring the given role (or administrator)."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.CheckFailure("This command can only be used in a server.")
        if not has_role_by_name(interaction.user, role_name):
            raise app_commands.CheckFailure(f"You need the **{role_name}** role to use this command.")
        return True
    return predicate


# Ready-made checks
requires_police = app_commands.check(role_check(ROLE_POLICE))
requires_supervisor = app_commands.check(role_check(ROLE_POLICE_SUPERVISOR))
requires_bank_staff = app_commands.check(role_check(ROLE_BANK_STAFF))
requires_revenue = app_commands.check(role_check(ROLE_REVENUE))
requires_sec = app_commands.check(role_check(ROLE_SEC))
requires_consumer = app_commands.check(role_check(ROLE_CONSUMER))
requires_curial = app_commands.check(role_check(ROLE_CURIAL))
requires_minister = app_commands.check(role_check(ROLE_MINISTER))
requires_journalist = app_commands.check(role_check(ROLE_JOURNALIST))
requires_customs = app_commands.check(role_check(ROLE_CUSTOMS))
