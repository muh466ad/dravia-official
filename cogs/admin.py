"""Dravia State Bot - Admin & Setup Commands"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os
import shutil

from config import COLOR_ACCENT, COLOR_GOLD, COLOR_CRIMSON, STARTING_BALANCE
from database import Database
from utils.calendar import stamp
from utils.logger import admin_log

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Roles created by /setup (Permissions Matrix, Part 21).
# Every role guarded by utils.checks.REQUIRED_ROLES must appear here, otherwise the
# commands it gates stay locked out with no way for a server owner to unblock them.
MANAGED_ROLES = [
    "Citizen", "Student", "Farmer", "Trader", "Business Owner",
    "Civil Servant", "Police Officer", "Sergeant", "Bank Staff",
    "Revenue Staff", "SEC", "Consumer Protection", "Customs Officer",
    "Curial", "Minister", "Admin", "Journalist", "Homeowner",
    # Expansion systems: military, intelligence, fire, diplomacy, immigration,
    # health, education, finance, patents, media and sport.
    "Soldier", "Agent", "Firefighter", "Diplomat", "Immigration Officer",
    "Doctor", "Professor", "Fund Manager", "Insurance Company",
    "Patent Officer", "Media Owner", "Tournament Organiser",
]

# Roles rendered in the authority colour instead of the default gold.
_AUTHORITY_ROLES = {
    "Police Officer", "Sergeant", "Minister", "Curial", "Admin", "SEC",
    "Soldier", "Firefighter", "Agent", "Customs Officer", "Immigration Officer",
}

# Authority roles ordered highest-first. /setup stacks these directly beneath the
# bot's own role so the Permissions Matrix holds: a member holding @Sergeant also
# satisfies @Police Officer, and @Admin sits above everything.
ROLE_HIERARCHY = [
    "Admin", "Minister", "Curial", "SEC", "Consumer Protection",
    "Customs Officer", "Revenue Staff", "Bank Staff", "Sergeant",
    "Police Officer", "Soldier", "Firefighter", "Agent",
    "Immigration Officer", "Diplomat", "Patent Officer",
    "Fund Manager", "Insurance Company", "Media Owner",
    "Tournament Organiser", "Journalist", "Doctor", "Professor",
]

# (channel name, purpose). These are the final names Discord receives.
CHANNELS = [
    ("gazette", "Government Gazette & announcements"),
    ("market", "Stock market & economy discussion"),
    ("dispatch", "Police dispatch & duty"),
    ("curia", "Curia legislative chamber"),
]

# Permissions Matrix applied to channels /setup creates.
#   None for `view`/`send` means "everyone" (left at the Discord default).
CHANNEL_MATRIX = {
    "gazette": {"view": None, "send": ["Admin", "Minister", "Curial", "Journalist"]},
    "market": {"view": None, "send": None},
    "dispatch": {
        "view": ["Admin", "Minister", "Police Officer", "Sergeant"],
        "send": ["Admin", "Minister", "Police Officer", "Sergeant"],
    },
    "curia": {
        "view": ["Admin", "Minister", "Curial", "Journalist"],
        "send": ["Admin", "Minister", "Curial", "Journalist"],
    },
}

_EMBED_FIELD_MAX = 1024

class Admin(commands.Cog):
    """Administrative commands."""
    
    admin_group = app_commands.Group(name="admin", description="Administrative commands")
    

    def __init__(self, bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)

    @app_commands.command(name="setup", description="Initial server configuration (Admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("❌ Run this in a server.", ephemeral=True)
            return

        # Provisioning is ~20 sequential REST calls and Discord expires an
        # interaction after 3s without a response, so defer up front and report
        # through followup once the work is done.
        await interaction.response.defer(ephemeral=True)

        me = interaction.guild.me
        perms = me.guild_permissions if me is not None else None
        missing_perms = []
        if perms is None or not perms.manage_roles:
            missing_perms.append("Manage Roles")
        if perms is None or not perms.manage_channels:
            missing_perms.append("Manage Channels")
        if missing_perms:
            msg = "❌ I need " + " and ".join(f"**{p}**" for p in missing_perms) + " to run setup."
            if me is not None:
                msg += (
                    f"\nGrant them to <@{me.id}> in **Server Settings → Roles**, then re-run `/setup`."
                )
            else:
                msg += "\nI could not read my own permissions in this server."
            admin_log.warning("Setup denied in %s: missing %s", interaction.guild.id, missing_perms)
            await interaction.followup.send(msg, ephemeral=True)
            return

        created_roles, failed_roles = [], []
        for role_name in MANAGED_ROLES:
            if discord.utils.get(interaction.guild.roles, name=role_name):
                continue
            try:
                await interaction.guild.create_role(
                    name=role_name,
                    color=COLOR_CRIMSON if role_name in _AUTHORITY_ROLES else COLOR_GOLD,
                    reason="Dravia /setup",
                )
                created_roles.append(role_name)
            except discord.Forbidden:
                # Usually the bot's highest role sits above the role being created.
                failed_roles.append(f"{role_name} (role hierarchy)")
                break
            except discord.HTTPException as exc:
                failed_roles.append(f"{role_name} ({exc.status} {exc.text})")

        created_channels, failed_channels, secured_channels = [], [], []
        for name, _purpose in CHANNELS:
            # Check every channel type: a category named "gazette" would otherwise
            # block creation and be reported as a phantom failure.
            if discord.utils.get(interaction.guild.channels, name=name):
                continue
            matrix = CHANNEL_MATRIX.get(name, {})
            overwrites = self._build_overwrites(interaction.guild, matrix)
            try:
                await interaction.guild.create_text_channel(
                    name, overwrites=overwrites, reason="Dravia /setup"
                )
                created_channels.append(name)
                if matrix.get("view"):
                    secured_channels.append(name)
            except discord.Forbidden:
                failed_channels.append(f"{name} (no access)")
            except discord.HTTPException as exc:
                failed_channels.append(f"{name} ({exc.status} {exc.text})")

        # Stack the authority roles just beneath the bot's own role. Roles are
        # created at the very bottom, so without this @Citizen would outrank
        # @Admin and the matrix would be inverted.
        positioned = await self._position_roles(interaction.guild, me, failed_roles)

        failures = failed_roles + failed_channels
        admin_log.info(
            "Setup run by %s in %s: roles=%s channels=%s positioned=%s secured=%s failures=%s",
            interaction.user.id, interaction.guild.id, created_roles, created_channels,
            positioned, secured_channels, failures,
        )

        def joined(items, empty):
            return (", ".join(items) or empty)[:_EMBED_FIELD_MAX]

        if failures:
            title, description, colour = (
                "⚠️ Server Setup Incomplete",
                "Some resources could not be created — see the failures below.",
                COLOR_GOLD,
            )
        else:
            title, description, colour = (
                "🛠️ Server Setup Complete",
                "The Republic of Dravia has been provisioned on this server.",
                COLOR_ACCENT,
            )

        embed = discord.Embed(title=title, description=description, color=colour)
        embed.add_field(
            name=f"Roles Created ({len(created_roles)})",
            value=joined(created_roles, "All roles already exist"),
            inline=False,
        )
        embed.add_field(
            name=f"Channels Created ({len(created_channels)})",
            value=joined(created_channels, "All channels already exist"),
            inline=False,
        )
        if positioned:
            embed.add_field(
                name="Role Hierarchy",
                value=joined(positioned, "None"),
                inline=False,
            )
        if secured_channels:
            embed.add_field(
                name="Permissions Matrix",
                value=joined(
                    [f"`{c}` restricted to the matrix roles" for c in secured_channels],
                    "None",
                ),
                inline=False,
            )
        if failures:
            embed.add_field(
                name="❌ Failures",
                value=joined(failures, "None"),
                inline=False,
            )
        embed.add_field(
            name="Next Steps",
            value="1. Assign roles per the Permissions Matrix\n2. Run `/help` to see all commands\n3. `/status` for system health",
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | Ministry of Administration")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @staticmethod
    def _build_overwrites(guild, matrix):
        """Translate a CHANNEL_MATRIX entry into Discord PermissionOverwrites.

        A `None` view/send list means the permission stays at the Discord default
        for @everyone. Senders always receive view + history, since Discord
        silently drops `send_messages` without it.
        """
        view, send = matrix.get("view"), matrix.get("send")
        everyone = guild.default_role
        everyone_can = view is None

        overwrites = {
            everyone: discord.PermissionOverwrite(
                view_channel=everyone_can,
                read_message_history=everyone_can,
                send_messages=everyone_can and send is None,
            )
        }
        for role_name in view or []:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, read_message_history=True
                )
        for role_name in send or []:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, read_message_history=True, send_messages=True
                )
        return overwrites

    async def _position_roles(self, guild, me, failed_roles):
        """Place authority roles in hierarchy order beneath the bot's top role.

        Returns the names actually moved. Roles already above the bot's top role
        are left alone - Discord will not let the bot reorder them.
        """
        moved = []
        if me is None:
            return moved
        top = me.top_role.position
        # Offset by the role's fixed rank in ROLE_HIERARCHY, not by how many
        # roles have moved so far: skipping an already-placed role would
        # otherwise shift the target of every role after it and corrupt the
        # hierarchy on a re-run.
        for rank, name in enumerate(ROLE_HIERARCHY):
            role = discord.utils.get(guild.roles, name=name)
            if role is None:
                continue
            target = top - 1 - rank
            if target < 1:
                break
            if role.position > top:
                failed_roles.append(
                    f"{name} sits above the bot's role - drag <@{me.id}> above it "
                    "in Server Settings → Roles, then re-run"
                )
                continue
            if role.position == target:
                continue
            try:
                await role.edit(position=target, reason="Dravia /setup")
                moved.append(name)
            except (discord.Forbidden, discord.HTTPException) as exc:
                failed_roles.append(f"{name} position ({exc.__class__.__name__})")
        return moved

    @admin_group.command(name="pay", description="Pay a citizen from the Treasury (Admin)")
    @app_commands.describe(user="Recipient", amount="Amount", reason="Reason")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_pay(self, interaction: discord.Interaction, user: discord.User, amount: int, reason: str = "Treasury payment"):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        await self.db.create_user(str(user.id))
        await self.db.add_balance(str(user.id), amount, "treasury", reason)
        admin_log.info("Treasury payment: %s -> %s amount=%s reason=%s", interaction.user.id, user.id, amount, reason)
        embed = discord.Embed(
            title="💰 Treasury Payment",
            description=f"{user.mention} received 🪙 **{amount:,}**",
            color=COLOR_GOLD,
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Authorised by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="set_balance", description="Set a citizen's balance (Admin)")
    @app_commands.describe(user="Citizen", amount="New balance")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_set_balance(self, interaction: discord.Interaction, user: discord.User, amount: int):
        if amount < 0:
            await interaction.response.send_message("❌ Balance cannot be negative.", ephemeral=True)
            return
        await self.db.create_user(str(user.id))
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amount, str(user.id)))
            await db.commit()
        admin_log.info("Balance set: %s -> %s by %s", user.id, amount, interaction.user.id)
        await interaction.response.send_message(
            f"✅ {user.mention}'s balance set to 🪙 **{amount:,}**.", ephemeral=True
        )

    @admin_group.command(name="log", description="View recent admin actions (Admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_log_view(self, interaction: discord.Interaction):
        lines = []
        try:
            with open(os.path.join("logs", "admin.log"), "r", encoding="utf-8") as f:
                lines = f.readlines()[-8:]
        except FileNotFoundError:
            lines = []
        embed = discord.Embed(title="🗂️ Recent Admin Actions", color=COLOR_ACCENT)
        embed.description = "```\n" + ("".join(lines) or "No admin actions logged yet.")[-1500:] + "\n```"
        embed.set_footer(text="Republic of Dravia | admin.log")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="roles", description="Show the Permissions Matrix (Admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_roles(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🔐 Permissions Matrix", color=COLOR_GOLD)
        embed.add_field(
            name="Open to @everyone",
            value="Economy, grants, housing applications, consumer complaints",
            inline=False,
        )
        embed.add_field(
            name="Role-gated commands",
            value=(
                "`@Citizen` voting, UBI claims\n"
                "`@Police Officer` police commands\n"
                "`@Sergeant+` supervisor commands\n"
                "`@Bank Staff` loan approval\n"
                "`@Revenue Staff` tax enforcement\n"
                "`@SEC` investigations\n"
                "`@Consumer Protection` consumer authority\n"
                "`@Curial` curia & audit commands\n"
                "`@Minister` departmental commands\n"
                "`@Admin` full system access"
            ),
            inline=False,
        )
        embed.set_footer(text="Republic of Dravia | /setup creates these roles")
        await interaction.response.send_message(embed=embed, ephemeral=True)


    # ---------------------------------------------------- system records
    @admin_group.command(name="backup", description="Snapshot the database to data/backups (Admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_backup(self, interaction: discord.Interaction):
        if not os.path.exists(DATABASE_PATH):
            await interaction.response.send_message(
                f"❌ Database not found at {DATABASE_PATH}.", ephemeral=True)
            return
        backup_dir = os.path.join(os.path.dirname(DATABASE_PATH) or "data", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp_name = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = os.path.join(backup_dir, f"dravia-{stamp_name}.db")
        shutil.copy2(DATABASE_PATH, target)
        size = os.path.getsize(target)
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO backups (backup_type, file_path, size, created_at, verified) "
                "VALUES (?, ?, ?, ?, 1)",
                ("Full", target, size, datetime.now().isoformat()),
            )
            backup_id = cursor.lastrowid
            await db.commit()
        admin_log.info("Backup %s created by %s (%s bytes)",
                       backup_id, interaction.user.id, size)
        embed = discord.Embed(
            title="💾 Backup Complete",
            description=f"Snapshot #{backup_id} written and verified.",
            color=COLOR_ACCENT,
        )
        embed.add_field(name="Size", value=f"{size:,} bytes", inline=True)
        embed.add_field(name="Path", value=target[-80:], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="backups", description="Recent database snapshots (Admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_backups(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT backup_id, backup_type, size, created_at, verified "
                "FROM backups ORDER BY backup_id DESC LIMIT 8"
            ) as cursor:
                rows = await cursor.fetchall()
        embed = discord.Embed(title="💾 Snapshots", color=COLOR_GOLD)
        if not rows:
            embed.description = "No snapshots yet — `/admin backup` makes the first."
        for backup_id, backup_type, size, created_at, verified in rows:
            mark = "verified" if verified else "unverified"
            embed.add_field(
                name=f"#{backup_id} {backup_type}",
                value=f"{size:,} bytes · {stamp(created_at)} · {mark}",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="flag", description="Raise an anti-cheat flag (Admin)")
    @app_commands.describe(user="Citizen to flag", details="What was observed")
    @app_commands.choices(kind=[app_commands.Choice(name=k, value=k)
                                for k in ("Economy", "Behaviour", "Exploit", "Other")])
    @app_commands.default_permissions(manage_guild=True)
    async def admin_flag(self, interaction: discord.Interaction, user: discord.User,
                         kind: str, details: str):
        details = " ".join(details.split())[:200]
        if not details:
            await interaction.response.send_message(
                "❌ Describe what you observed.", ephemeral=True)
            return
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO anti_cheat_flags (user_id, flag_type, details, status, flagged_at) "
                "VALUES (?, ?, ?, 'open', ?)",
                (str(user.id), kind, details, datetime.now().isoformat()),
            )
            flag_id = cursor.lastrowid
            await db.commit()
        admin_log.info("Anti-cheat flag %s (%s) on %s by %s",
                       flag_id, kind, user.id, interaction.user.id)
        embed = discord.Embed(
            title="🚩 Flag Raised",
            description=f"Flag #{flag_id} opened against **{user}** ({kind}).",
            color=COLOR_CRIMSON,
        )
        embed.add_field(name="Observed", value=details, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="flags", description="Open anti-cheat flags (Admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_flags(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT flag_id, user_id, flag_type, details, flagged_at "
                "FROM anti_cheat_flags WHERE status = 'open' ORDER BY flag_id DESC LIMIT 15"
            ) as cursor:
                rows = await cursor.fetchall()
        embed = discord.Embed(title="🚩 Open Flags", color=COLOR_CRIMSON)
        if not rows:
            embed.description = "No open flags. The Republic behaves."
        for flag_id, user_id, kind, details, flagged_at in rows:
            embed.add_field(
                name=f"#{flag_id} {kind} — <@{user_id}>",
                value=f"{details}\n{stamp(flagged_at)}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="flag_close", description="Close an anti-cheat flag (Admin)")
    @app_commands.describe(flag_id="Flag to close")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_flag_close(self, interaction: discord.Interaction, flag_id: int):
        async with await self.db.get_connection() as db:
            cursor = await db.execute(
                "UPDATE anti_cheat_flags SET status = 'closed' WHERE flag_id = ? "
                "AND status = 'open'", (flag_id,)
            )
            changed = cursor.rowcount
            await db.commit()
        if changed != 1:
            await interaction.response.send_message(
                f"❌ No open flag #{flag_id}.", ephemeral=True)
            return
        admin_log.info("Anti-cheat flag %s closed by %s", flag_id, interaction.user.id)
        embed = discord.Embed(title="🚩 Flag Closed",
                              description=f"Flag #{flag_id} resolved.",
                              color=COLOR_ACCENT)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="syslog", description="Record a system log entry (Admin)")
    @app_commands.describe(message="What happened")
    @app_commands.choices(severity=[app_commands.Choice(name=s, value=s)
                                    for s in ("info", "warning", "critical")])
    @app_commands.default_permissions(manage_guild=True)
    async def admin_syslog(self, interaction: discord.Interaction, message: str,
                           severity: str = "info"):
        message = " ".join(message.split())[:200]
        if not message:
            await interaction.response.send_message(
                "❌ The entry is empty.", ephemeral=True)
            return
        async with await self.db.get_connection() as db:
            await db.execute(
                "INSERT INTO system_logs (log_type, message, severity, created_at) "
                "VALUES ('admin', ?, ?, ?)",
                (message, severity, datetime.now().isoformat()),
            )
            await db.commit()
        admin_log.info("System log (%s) by %s: %s", severity, interaction.user.id, message)
        embed = discord.Embed(title="📒 Entry Recorded",
                              description=f"**{severity}** — {message}",
                              color=COLOR_ACCENT)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="logs", description="Recent system log entries (Admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def admin_logs(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT log_id, log_type, message, severity, created_at "
                "FROM system_logs ORDER BY log_id DESC LIMIT 10"
            ) as cursor:
                rows = await cursor.fetchall()
        embed = discord.Embed(title="📒 System Log", color=COLOR_GOLD)
        if not rows:
            embed.description = "No entries recorded. `/admin syslog` writes one."
        for log_id, log_type, message, severity, created_at in rows:
            embed.add_field(
                name=f"#{log_id} {severity} ({log_type})",
                value=f"{message}\n{stamp(created_at)}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
