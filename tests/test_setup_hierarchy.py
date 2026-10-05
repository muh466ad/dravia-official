"""Behavioural tests for /setup's role hierarchy and Permissions Matrix.

These import the cog for real (unlike test_setup_roles.py, which only parses
source), so config.py must find a token first.

Tests are plain sync functions driving asyncio.run() so the suite needs no
async plugin (pytest-asyncio autoloading is slow in this environment).

Run with:
    python -m pytest tests/ -q
"""
import asyncio
import os

# config.py raises on import without these; the values are never used here.
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "0")

import discord  # noqa: E402
import pytest  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from cogs.admin import Admin, CHANNEL_MATRIX, ROLE_HIERARCHY  # noqa: E402


class FakeRole:
    def __init__(self, name, guild=None):
        self.name = name
        self.guild = guild
        self.position = 0

    async def edit(self, position=None, reason=None, **kwargs):
        if position is not None:
            self.guild._move(self, position)

    def __repr__(self):
        return f"{self.name}@{self.position}"


class FakeGuild:
    """Bottom-to-top role list where index == role.position.

    Mirrors Discord: a newly created role lands at the bottom, which pushes
    every role above it up one position.
    """

    def __init__(self, filler=(), bot_rank=None, **perms):
        self.roles = [FakeRole("@everyone")]
        for name in filler:
            self._insert(FakeRole(name, self), 1)
        self.bot_role = FakeRole("DraviaBot", self)
        self._insert(self.bot_role, bot_rank if bot_rank is not None else len(self.roles))
        self._reindex()
        self.default_role = self.roles[0]
        self.channels = []
        self.id = 1
        self.me = MagicMock()
        self.me.id = 99
        self.me.top_role = self.bot_role
        self.me.guild_permissions = MagicMock(**{
            "manage_roles": True, "manage_channels": True, **perms,
        })

    def _insert(self, role, index):
        role.guild = self
        self.roles.insert(index, role)

    def _reindex(self):
        for i, r in enumerate(self.roles):
            r.position = i

    def _move(self, role, index):
        self.roles.remove(role)
        self.roles.insert(max(1, min(index, len(self.roles))), role)
        self._reindex()

    async def create_role(self, name, color=None, reason=None):
        role = FakeRole(name, self)
        self._insert(role, 1)          # Discord puts new roles at the bottom
        self._reindex()
        return role

    async def create_text_channel(self, name, overwrites=None, reason=None):
        ch = MagicMock()
        ch.name = name
        ch.overwrites = overwrites
        self.channels.append(ch)
        return ch

    def order(self):
        return [r.name for r in sorted(self.roles, key=lambda r: r.position)]

    def role(self, name):
        return next((r for r in self.roles if r.name == name), None)


@pytest.fixture(autouse=True)
def _patch_utils_get(monkeypatch):
    """discord.utils.get over plain lists, as the cog uses it."""
    monkeypatch.setattr(
        discord.utils, "get",
        lambda seq, name=None: next(
            (x for x in seq if getattr(x, "name", None) == name), None
        ),
    )


def _interaction(guild):
    i = MagicMock()
    i.guild = guild
    i.user = MagicMock()
    i.user.id = 5
    sent = []

    async def send_message(*a, **k):
        sent.append(("response", a, k))

    async def defer(ephemeral=True):
        sent.append(("defer",))

    async def followup(*a, **k):
        sent.append(("followup", a, k))

    i.response.send_message = send_message
    i.response.defer = defer
    i.followup.send = followup
    i._sent = sent
    return i


def _embed(sent):
    _, args, kwargs = sent[-1]
    return args[0] if args else kwargs["embed"]


def _fields(embed):
    return {f.name: f.value for f in embed.fields}


async def _run(admin, guild):
    interaction = _interaction(guild)
    await admin.setup.callback(admin, interaction)
    return _embed(interaction._sent)


def _setup(admin, guild):
    """Run /setup once against `guild` and return the reply embed."""
    return asyncio.run(_run(admin, guild))


@pytest.fixture
def admin():
    return Admin(MagicMock())


def _authority_order(guild):
    return [n for n in guild.order() if n in ROLE_HIERARCHY]


# The access each channel is SUPPOSED to have, written out independently of
# CHANNEL_MATRIX. Reading expectations back out of the constant the code
# consumes would be circular - editing the matrix would silently edit the test.
EXPECTED_ACCESS = {
    "gazette": (True, False, {"Admin", "Minister", "Curial", "Journalist"}),
    "market": (True, True, set()),
    "dispatch": (False, False, {"Admin", "Minister", "Police Officer", "Sergeant"}),
    "curia": (False, False, {"Admin", "Minister", "Curial", "Journalist"}),
}


# ------------------------------------------------------------- hierarchy
def test_authority_roles_land_in_matrix_order(admin):
    guild = FakeGuild(filler=("Mods", "VIP"))
    _setup(admin, guild)

    authority = _authority_order(guild)
    assert authority == list(reversed(ROLE_HIERARCHY)), (
        f"expected bottom-to-top {list(reversed(ROLE_HIERARCHY))}, got {authority}"
    )


def test_admin_outranks_curial(admin):
    guild = FakeGuild()
    _setup(admin, guild)
    assert guild.order().index("Admin") > guild.order().index("Curial")


def test_authority_roles_stay_below_the_bot_role(admin):
    guild = FakeGuild(filler=("Mods", "VIP"))
    _setup(admin, guild)
    bot_pos = guild.bot_role.position
    for name in ROLE_HIERARCHY:
        assert guild.role(name).position < bot_pos, f"{name} outranked the bot"


def test_reruns_do_not_disturb_the_hierarchy(admin):
    """Regression: offsetting targets by the number of roles moved so far
    desynchronised on every re-run, because an already-placed role is skipped
    without incrementing the offset - silently inverting the hierarchy."""
    guild = FakeGuild(filler=("Mods", "VIP"))
    _setup(admin, guild)
    settled = guild.order()

    for _ in range(3):
        _setup(admin, guild)
        assert guild.order() == settled, (
            f"re-run changed the role order:\n  was {settled}\n  now {guild.order()}"
        )


def test_rerun_reports_no_role_moves(admin):
    guild = FakeGuild()
    _setup(admin, guild)
    embed = _setup(admin, guild)
    assert "Role Hierarchy" not in _fields(embed), "nothing should move on a re-run"


# ------------------------------------------------------- permission matrix
def test_restricted_channels_hide_from_everyone(admin):
    guild = FakeGuild()
    _setup(admin, guild)

    for ch in guild.channels:
        matrix = CHANNEL_MATRIX[ch.name]
        everyone = ch.overwrites[guild.default_role]
        if matrix.get("view"):
            assert everyone.view_channel is False, f"#{ch.name} leaked to @everyone"
            assert everyone.send_messages is False, f"#{ch.name} leaked to @everyone"
        else:
            assert everyone.view_channel is True, f"#{ch.name} unreadable by @everyone"


def test_every_matrix_role_can_view_and_send(admin):
    guild = FakeGuild()
    _setup(admin, guild)

    for ch in guild.channels:
        matrix = CHANNEL_MATRIX[ch.name]
        if not matrix.get("view"):
            continue
        expected = set(matrix["view"])
        granted = {
            role.name for role, perm in ch.overwrites.items()
            if role is not guild.default_role and perm.send_messages
        }
        assert granted == expected, (
            f"#{ch.name} grants {sorted(granted)}, matrix says {sorted(expected)}"
        )


def test_senders_also_receive_view_and_history(admin):
    """Discord silently ignores send_messages without view + history."""
    guild = FakeGuild()
    _setup(admin, guild)

    for ch in guild.channels:
        for role, perm in ch.overwrites.items():
            if role is guild.default_role or not perm.send_messages:
                continue
            assert perm.view_channel is True, f"#{ch.name} @{role.name} can send but not view"
            assert perm.read_message_history is True, f"#{ch.name} @{role.name} can send but not read"


def test_open_channels_are_left_public(admin):
    guild = FakeGuild()
    _setup(admin, guild)

    market = next(c for c in guild.channels if c.name == "market")
    everyone = market.overwrites[guild.default_role]
    assert everyone.view_channel and everyone.send_messages


def test_gazette_is_read_only_for_the_public(admin):
    guild = FakeGuild()
    _setup(admin, guild)

    gazette = next(c for c in guild.channels if c.name == "gazette")
    everyone = gazette.overwrites[guild.default_role]
    assert everyone.view_channel is True, "gazette should be publicly readable"
    assert everyone.send_messages is False, "public should not post to the gazette"


def test_every_channel_matches_the_intended_permissions_matrix(admin):
    """Pins the Permissions Matrix from the README, independent of the code."""
    guild = FakeGuild()
    _setup(admin, guild)

    created = {c.name for c in guild.channels}
    assert created == set(EXPECTED_ACCESS), (
        f"/setup created {sorted(created)}, expected {sorted(EXPECTED_ACCESS)}"
    )

    for ch in guild.channels:
        public_read, public_write, posters = EXPECTED_ACCESS[ch.name]
        everyone = ch.overwrites[guild.default_role]
        assert everyone.view_channel is public_read, f"#{ch.name} public read"
        assert everyone.send_messages is public_write, f"#{ch.name} public write"

        granted = {
            role.name for role, perm in ch.overwrites.items()
            if role is not guild.default_role and perm.send_messages
        }
        assert granted == posters, (
            f"#{ch.name} lets {sorted(granted)} post, intended {sorted(posters)}"
        )