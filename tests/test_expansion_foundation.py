"""Tests for the expansion foundation: migration, roles, embeds and validation.

Run with:
    python -m pytest tests/ -q
"""
import asyncio
import os
import re
from datetime import date, timedelta

import pytest

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "0")

import migrate  # noqa: E402
from cogs.admin import MANAGED_ROLES, ROLE_HIERARCHY  # noqa: E402
from utils import checks  # noqa: E402
from utils.embeds import (  # noqa: E402
    MAX_FIELDS,
    MAX_FIELD_NAME,
    MAX_FIELD_VALUE,
    MAX_TITLE,
    MAX_TOTAL,
    DraviaEmbed,
    error,
    money_line,
    success,
)
from utils.validation import (  # noqa: E402
    ValidationError,
    amount,
    check_funds,
    choice,
    discord_id,
    dravian_date,
    pagination,
    percentage,
    record_id,
    text,
    whole_number,
)


# ------------------------------------------------------------- migration
def _tables(db_path):
    import aiosqlite

    async def go():
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cur:
                return {r[0] for r in await cur.fetchall()}
    return asyncio.run(go())


def _columns(db_path, table):
    import aiosqlite

    async def go():
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(f"PRAGMA table_info({table})") as cur:
                return [r[1] for r in await cur.fetchall()]
    return asyncio.run(go())


@pytest.fixture
def migrated(tmp_path):
    """A database that has had the expansion migration applied."""
    db_path = str(tmp_path / "test.db")
    asyncio.run(migrate.apply(db_path))
    return db_path


@pytest.fixture
def legacy(tmp_path):
    """A pre-expansion database with cooldowns history, as a live server has."""
    import aiosqlite
    db_path = str(tmp_path / "legacy.db")

    async def go():
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    user_id TEXT, command TEXT, last_claimed DATE,
                    PRIMARY KEY (user_id, command))""")
            # Seed relative to today, the way a live server's rows look: /daily
            # claimed today, /weekly a week ago. Hardcoding dates would make the
            # preservation assertions below true only on the day they were written.
            daily = date.today().isoformat()
            weekly = (date.today() - timedelta(days=7)).isoformat()
            await db.execute("INSERT INTO cooldowns VALUES ('111','daily',?)", (daily,))
            await db.execute("INSERT INTO cooldowns VALUES ('111','weekly',?)", (weekly,))
            await db.commit()
    asyncio.run(go())
    return db_path


def test_migration_creates_every_spec_table(migrated):
    tables = _tables(migrated)
    missing = [name for name, _ in migrate.NEW_TABLES if name not in tables]
    assert not missing, f"migration did not create: {missing}"


def test_migration_is_idempotent(tmp_path):
    db_path = str(tmp_path / "twice.db")
    asyncio.run(migrate.apply(db_path))
    before = _tables(db_path)
    asyncio.run(migrate.apply(db_path))
    assert _tables(db_path) == before, "second run changed the schema"


def test_migration_adds_expires_at_without_recreating_cooldowns(legacy):
    """`cogs/economy.py` reads `last_claimed` for /daily and /weekly, so the
    table must be upgraded in place, never dropped and recreated."""
    asyncio.run(migrate.apply(legacy))
    columns = _columns(legacy, "cooldowns")
    assert "expires_at" in columns
    assert "last_claimed" in columns


def test_migration_preserves_existing_cooldown_history(legacy):
    import aiosqlite

    asyncio.run(migrate.apply(legacy))

    async def go():
        async with aiosqlite.connect(legacy) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM cooldowns WHERE user_id='111' ORDER BY command"
            ) as cur:
                return {r["command"]: dict(r) for r in await cur.fetchall()}
    rows = asyncio.run(go())

    # Economy compares this against date.today().isoformat(), so a migration
    # that rewrote (or dropped) the row would hand citizens a fresh /daily.
    assert rows["daily"]["last_claimed"] == date.today().isoformat()
    assert rows["weekly"]["last_claimed"] == (date.today() - timedelta(days=7)).isoformat()


def test_migration_backfills_expiry_for_legacy_rows(legacy):
    import aiosqlite

    asyncio.run(migrate.apply(legacy))

    async def go():
        async with aiosqlite.connect(legacy) as db:
            async with db.execute(
                "SELECT expires_at FROM cooldowns WHERE command='daily'"
            ) as cur:
                return (await cur.fetchone())[0]
    assert asyncio.run(go()) == f"{date.today().isoformat()} 23:59:59"


def test_migration_records_its_version(migrated):
    import aiosqlite

    async def go():
        async with aiosqlite.connect(migrated) as db:
            async with db.execute("SELECT version FROM schema_migrations") as cur:
                return [r[0] for r in await cur.fetchall()]
    assert asyncio.run(go()) == ["001_expansion"]


def test_dry_run_changes_nothing(tmp_path):
    db_path = str(tmp_path / "dry.db")
    asyncio.run(migrate.apply(db_path, dry_run=True))
    tables = _tables(db_path)
    assert "military_units" not in tables, "dry run created a table"
    assert "schema_migrations" in tables


def test_no_new_table_drops_an_existing_one(migrated):
    """Guards against a future migration using plain CREATE TABLE, which fails
    outright on an existing name and would abort the whole run."""
    for name, ddl in migrate.NEW_TABLES:
        assert "IF NOT EXISTS" in ddl, f"{name} is not guarded by IF NOT EXISTS"


def test_cooldowns_table_is_not_in_the_new_table_list(legacy):
    """cooldowns predates the expansion; recreating it would drop history."""
    names = [n for n, _ in migrate.NEW_TABLES]
    assert "cooldowns" not in names


def test_foreign_keys_are_actually_enforced(tmp_path, monkeypatch):
    """SQLite ignores FOREIGN KEY clauses unless the pragma is ON, per
    connection. Without this the whole expansion schema is unenforced."""
    import database

    db_path = str(tmp_path / "fk.db")
    asyncio.run(migrate.apply(db_path))
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)

    async def go():
        db = database.Database(db_path)
        async with await db.get_connection() as conn:
            async with conn.execute("PRAGMA foreign_keys") as cur:
                enabled = (await cur.fetchone())[0]
            assert enabled == 1, "PRAGMA foreign_keys is not on"

            # A dangling reference must be refused.
            with pytest.raises(Exception):
                await conn.execute(
                    "INSERT INTO courses (name, university_id) VALUES ('x', 999999)"
                )
            # A NULL reference stays legal, as SQLite intends.
            await conn.execute("INSERT INTO courses (name) VALUES ('null_ref')")
    asyncio.run(go())


def test_cooldown_helpers_work_after_migration(tmp_path, monkeypatch):
    import database

    db_path = str(tmp_path / "cd.db")
    asyncio.run(migrate.apply(db_path))
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)

    async def go():
        db = database.Database(db_path)
        assert await db.set_expiring_cooldown("7", "gambling", 60) is True
        remaining = await db.cooldown_remaining("7", "gambling")
        assert 50 < remaining <= 60, f"expected ~60s left, got {remaining}"
        assert await db.cooldown_remaining("7", "never_used") == 0.0
        # The day-granular path economy depends on must be untouched.
        await db.set_cooldown("7", "daily")
        assert await db.get_cooldown("7", "daily") == date.today().isoformat()
    asyncio.run(go())


def test_cooldown_helpers_degrade_without_the_migration(tmp_path, monkeypatch):
    """A server that has not run `python migrate.py` must not crash on boot."""
    import database

    db_path = str(tmp_path / "nomigrate.db")
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)

    async def go():
        await database.init_db()
        db = database.Database(db_path)
        await db.set_cooldown("7", "daily")
        assert await db.get_cooldown("7", "daily") == date.today().isoformat()
        assert await db.set_expiring_cooldown("7", "gambling", 60) is False
        assert await db.cooldown_remaining("7", "gambling") == 0.0
    asyncio.run(go())


# ------------------------------------------------------------------ roles
NEW_ROLES = [
    "Soldier", "Agent", "Firefighter", "Diplomat", "Immigration Officer",
    "Doctor", "Professor", "Fund Manager", "Insurance Company",
    "Patent Officer", "Media Owner", "Tournament Organiser",
]


@pytest.mark.parametrize("role", NEW_ROLES)
def test_expansion_role_is_created_by_setup(role):
    assert role in MANAGED_ROLES, f"/setup will not create @{role}"


@pytest.mark.parametrize("role", NEW_ROLES)
def test_expansion_role_is_positioned_in_the_hierarchy(role):
    assert role in ROLE_HIERARCHY, f"@{role} would sit below unrelated roles"


@pytest.mark.parametrize("name", [n for n in dir(checks) if n.startswith("ROLE_")])
def test_every_role_constant_is_created_by_setup(name):
    role = getattr(checks, name)
    assert role in MANAGED_ROLES, f"{name}={role!r} gates commands but /setup never creates it"


def _roles_covered_by_ready_checks():
    """Role names reachable from the ready-made `requires_*` predicates.

    Reads the closure graph rather than matching attribute names, because the
    two do not always correspond (ROLE_POLICE_SUPERVISOR is served by
    requires_supervisor). `app_commands.check()` wraps the predicate in its own
    decorator, so the search has to follow nested closures.
    """
    found = set()
    seen = set()

    def walk(obj, depth=0):
        if depth > 4 or id(obj) in seen:
            return
        seen.add(id(obj))
        for cell in (getattr(obj, "__closure__", None) or []):
            value = cell.cell_contents
            if isinstance(value, str):
                found.add(value)
            elif callable(value):
                walk(value, depth + 1)

    for name in dir(checks):
        if name.startswith("requires_"):
            walk(getattr(checks, name))
    return found


def test_every_role_constant_has_a_ready_made_check():
    declared = {getattr(checks, n) for n in dir(checks) if n.startswith("ROLE_")}
    covered = _roles_covered_by_ready_checks()
    uncovered = sorted(declared - covered)
    assert not uncovered, (
        f"no requires_* check accepts these roles: {uncovered}. "
        "A new cog would have to hand-roll app_commands.check(role_check(...))."
    )


def test_hierarchy_starts_with_admin():
    assert ROLE_HIERARCHY[0] == "Admin"


def test_hierarchy_has_no_duplicates():
    assert len(ROLE_HIERARCHY) == len(set(ROLE_HIERARCHY))


def test_hierarchy_is_positionable_on_a_realistic_server():
    """Each authority role needs its own slot beneath the bot's role."""
    assert len(ROLE_HIERARCHY) <= 30, "would exhaust slots on a small server"


# ----------------------------------------------------------------- embeds
def test_embed_truncates_title_and_description():
    e = DraviaEmbed(title="T" * 900, description="D" * 9000)
    assert len(e.title) <= MAX_TITLE
    assert len(e.description) <= 4096


def test_embed_truncates_field_name_and_value():
    e = DraviaEmbed().add_field("N" * 900, "V" * 4000)
    assert len(e.fields[0].name) <= MAX_FIELD_NAME
    assert len(e.fields[0].value) <= MAX_FIELD_VALUE


def test_embed_never_exceeds_the_field_count_limit():
    e = DraviaEmbed()
    for i in range(60):
        e.add_field(f"f{i}", "value")
    assert len(e.fields) <= MAX_FIELDS


def test_embed_never_exceeds_the_total_character_limit():
    e = DraviaEmbed(description="D" * 4000)
    for i in range(30):
        e.add_field("n" * 100, "v" * 1000)
    assert e._spent() <= MAX_TOTAL


def test_embed_field_value_is_never_blank():
    """Discord rejects a message whose field value is empty."""
    assert DraviaEmbed().add_field("n", "   ").fields[0].value


def test_embed_never_exceeds_limits_with_unicode():
    """Character count, not byte count, is what Discord enforces."""
    e = DraviaEmbed().add_field("é" * 900, "🪙" * 4000)
    assert len(e.fields[0].name) <= MAX_FIELD_NAME
    assert len(e.fields[0].value) <= MAX_FIELD_VALUE


def test_error_embed_is_marked():
    assert error("Nope").title.startswith("❌")


def test_success_embed_uses_no_crimson():
    from config import COLOR_CRIMSON
    assert success("Done").color != COLOR_CRIMSON


def test_money_line_uses_the_ovi_symbol():
    assert "🪙" in money_line(1250)
    assert "1,250" in money_line(1250)


# ------------------------------------------------------------- validation
@pytest.mark.parametrize("bad", ["abc", "12.5", "", None, "1e5"])
def test_amount_rejects_non_integers(bad):
    with pytest.raises(ValidationError):
        amount(bad)


@pytest.mark.parametrize("bad", [0, -1, -10000])
def test_amount_rejects_non_positive(bad):
    with pytest.raises(ValidationError):
        amount(bad)


def test_amount_accepts_a_valid_value():
    assert amount("500") == 500


def test_amount_enforces_a_ceiling():
    with pytest.raises(ValidationError):
        amount(5000, maximum=1000)


def test_whole_number_allows_zero_and_negative():
    assert whole_number(0) == 0
    assert whole_number(-5) == -5


def test_record_id_rejects_zero_and_negatives():
    with pytest.raises(ValidationError):
        record_id(0)


def test_percentage_rejects_out_of_range():
    with pytest.raises(ValidationError):
        percentage(150)
    with pytest.raises(ValidationError):
        percentage(-1)
    assert percentage("2.5") == 2.5
    assert percentage("2.5%") == 2.5


def test_text_collapses_whitespace_and_trims():
    assert text("  a   b  ") == "a b"


def test_text_enforces_bounds():
    with pytest.raises(ValidationError):
        text("")
    with pytest.raises(ValidationError):
        text("x" * 501)


def test_text_error_names_the_field():
    with pytest.raises(ValidationError) as exc:
        text("", field="Company name")
    assert "Company name" in str(exc.value)


def test_choice_is_case_insensitive_and_returns_canonical_case():
    assert choice("conservative", ["Conservative", "Growth"]) == "Conservative"


def test_choice_lists_valid_options_when_wrong():
    with pytest.raises(ValidationError) as exc:
        choice("nope", ["Conservative", "Growth"])
    assert "Conservative" in str(exc.value)


def test_dravian_date_parses_documented_format():
    assert dravian_date("15/03/1998").year == 1998


@pytest.mark.parametrize("bad", ["32/01/1998", "not a date", "1998-13-01"])
def test_dravian_date_rejects_nonsense(bad):
    with pytest.raises(ValidationError):
        dravian_date(bad)


def test_dravian_date_rejects_the_future_unless_allowed():
    future = "01/01/2999"
    with pytest.raises(ValidationError):
        dravian_date(future)
    assert dravian_date(future, future_okay=True).year == 2999


@pytest.mark.parametrize("bad", ["nope", "123", "", "9" * 25])
def test_discord_id_rejects_non_snowflakes(bad):
    with pytest.raises(ValidationError):
        discord_id(bad)


def test_check_funds_names_the_shortfall():
    with pytest.raises(ValidationError) as exc:
        check_funds(100, 500)
    assert "400" in str(exc.value)


def test_check_funds_allows_exact_balance():
    check_funds(500, 500)


def test_pagination_clamps_out_of_range_pages():
    assert pagination(0) == 1
    assert pagination(-5) == 1
    assert pagination(999, per_page=10, total=25) == 3


def test_pagination_handles_no_results():
    assert pagination(1, total=0) == 1