"""Tests for the achievements cog (expansion system E3).

Run with:
    python -m pytest tests/ -q
"""
import asyncio
import os

import pytest

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "0")

import database  # noqa: E402
import migrate  # noqa: E402
from cogs.achievements import ACHIEVEMENTS, Achievements  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402


@pytest.fixture
def cog(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ach.db")
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)
    asyncio.run(database.init_db())
    asyncio.run(migrate.apply(db_path))
    return Achievements(MagicMock())


def _interaction(uid="1"):
    i = MagicMock()
    i.user = MagicMock()
    i.user.id = uid
    sent = []

    async def send_message(*a, **k):
        sent.append((a, k))

    i.response.send_message = send_message
    i._sent = sent
    return i


def _embed(interaction):
    return interaction._sent[-1][1]["embed"]


async def _run(cog, command, *args, uid="1"):
    interaction = _interaction(uid)
    await command.callback(cog, interaction, *args)
    return _embed(interaction)


# ------------------------------------------------------------------ data
def test_achievement_catalog_is_well_formed():
    names = [n for n, _, _, _ in ACHIEVEMENTS]
    assert len(names) == len(set(names)), "duplicate achievement names"
    for name, desc, reward, req in ACHIEVEMENTS:
        assert name.strip() and desc.strip() and req.strip()


def test_all_rewards_are_positive():
    for _, _, reward, _ in ACHIEVEMENTS:
        assert reward > 0


# ------------------------------------------------------------ behaviour
def test_nothing_unlocks_before_qualifying(cog):
    assert asyncio.run(cog.evaluate("1")) == []


def test_threshold_achievement_unlocks(cog):
    async def go():
        await cog.db.create_user("1")
        await cog.credit("1", 1000, "test", "seed")
        return await cog.evaluate("1")
    assert "First 1,000 Ovi" in asyncio.run(go())


def test_evaluate_is_idempotent(cog):
    """Re-running must not re-award or duplicate rows."""
    async def go():
        await cog.db.create_user("1")
        await cog.credit("1", 1000, "test", "seed")
        first = await cog.evaluate("1")
        second = await cog.evaluate("1")
        async with await cog.db.get_connection() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM player_achievements WHERE user_id='1'"
            ) as cur:
                rows = (await cur.fetchone())[0]
        return first, second, rows
    first, second, rows = asyncio.run(go())
    assert first == ["First 1,000 Ovi"]
    assert second == [], "already-unlocked achievement was reported again"
    assert rows == 1


def test_claim_pays_the_reward_once(cog):
    async def go():
        await cog.db.create_user("1")
        await cog.credit("1", 1000, "test", "seed")
        await cog.evaluate("1")
        before = await cog.balance_of("1")
        await _run(cog, cog.achievements_claim, "First 1,000 Ovi")
        after = await cog.balance_of("1")
        return before, after
    before, after = asyncio.run(go())
    assert after - before == 100


def test_second_claim_does_not_pay_again(cog):
    async def go():
        await cog.db.create_user("1")
        await cog.credit("1", 1000, "test", "seed")
        await cog.evaluate("1")
        await _run(cog, cog.achievements_claim, "First 1,000 Ovi")
        after_first = await cog.balance_of("1")
        embed = await _run(cog, cog.achievements_claim, "First 1,000 Ovi")
        return after_first, await cog.balance_of("1"), embed
    after_first, after_second, embed = asyncio.run(go())
    assert after_first == after_second, "achievement paid out twice"
    assert "already" in embed.description.lower()


def test_claim_refuses_an_unowned_achievement(cog):
    async def go():
        await cog.db.create_user("1")
        return await _run(cog, cog.achievements_claim, "Millionaire")
    embed = asyncio.run(go())
    assert "not" in embed.description.lower() or "unlock" in embed.description.lower()


def test_claiming_unknown_name_is_handled(cog):
    async def go():
        await cog.db.create_user("1")
        return await _run(cog, cog.achievements_claim, "No Such Achievement")
    embed = asyncio.run(go())
    assert embed.title.startswith("❌")


# ------------------------------------------------------------- rendering
def test_list_shows_the_whole_catalog(cog):
    embed = asyncio.run(_run(cog, cog.achievements_list))
    assert len(embed.fields) == len(ACHIEVEMENTS)


def test_mine_reports_nothing_when_empty(cog):
    async def go():
        await cog.db.create_user("1")
        return await _run(cog, cog.achievements_mine)
    embed = asyncio.run(go())
    assert "no achievement" in embed.title.lower()


def test_progress_lists_what_is_locked(cog):
    async def go():
        await cog.db.create_user("1")
        return await _run(cog, cog.achievements_progress)
    embed = asyncio.run(go())
    assert len(embed.fields) == len(ACHIEVEMENTS) + 1  # + balance field


def test_embeds_stay_within_discord_limits(cog):
    """A player-authored achievement name must not produce an illegal embed."""
    async def go():
        await cog.db.create_user("1")
        return await _run(cog, cog.achievements_claim, "A" * 4000)
    embed = asyncio.run(go())
    assert len(embed.title) <= 256
    for f in embed.fields:
        assert len(f.name) <= 256 and len(f.value) <= 1024