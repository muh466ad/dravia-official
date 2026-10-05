"""Dravia State Bot - Database Migrations

Applies schema changes to the same SQLite file the bot uses. Every migration is
idempotent and tracked in `schema_migrations`, so re-running is safe.

Usage:
    python migrate.py            # apply all pending migrations
    python migrate.py --dry-run  # report what would run, touch nothing
    python migrate.py --status   # list applied / pending migrations

Notes
-----
* Every CREATE TABLE uses IF NOT EXISTS. The bot's `init_db()` already creates
  tables on startup, so the same names may already exist.
* `cooldowns` is UPGRADED in place, not recreated. It predates this migration
  and holds `last_claimed DATE`, which `cogs/economy.py` compares against
  `date.today().isoformat()` for daily/weekly claims. Recreating it would drop
  that history and break `/daily` and `/weekly`, so the second-based cooldowns
  from system F2 use a new `expires_at` column alongside it.
* SQLite does not enforce FOREIGN KEY clauses unless `PRAGMA foreign_keys=ON`
  is set per connection. `Database.get_connection()` now sets it; this module
  verifies the existing data is clean before switching enforcement on.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime

import aiosqlite

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# --------------------------------------------------------------- new tables
# (table_name, DDL). Mirrors the expansion schema; deliberately IF NOT EXISTS.
NEW_TABLES: list[tuple[str, str]] = [
    ("military_units", """
        CREATE TABLE IF NOT EXISTS military_units (
            unit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, branch TEXT, commander_id TEXT, location TEXT,
            strength INTEGER DEFAULT 0, status TEXT DEFAULT 'active')"""),

    ("intel_missions", """
        CREATE TABLE IF NOT EXISTS intel_missions (
            mission_id INTEGER PRIMARY KEY AUTOINCREMENT,
            agency TEXT, target TEXT, objective TEXT,
            status TEXT DEFAULT 'active', classification TEXT,
            authorized_by TEXT, started_at DATE, completed_at DATE)"""),

    ("fire_incidents", """
        CREATE TABLE IF NOT EXISTS fire_incidents (
            incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT, severity TEXT, reported_at DATETIME,
            resolved_at DATETIME, responding_unit TEXT)"""),

    ("visas", """
        CREATE TABLE IF NOT EXISTS visas (
            visa_id INTEGER PRIMARY KEY AUTOINCREMENT,
            applicant_id TEXT, visa_type TEXT, reason TEXT,
            issued_at DATE, expires_at DATE, status TEXT DEFAULT 'pending')"""),

    ("embassies", """
        CREATE TABLE IF NOT EXISTS embassies (
            embassy_id INTEGER PRIMARY KEY AUTOINCREMENT,
            nation TEXT UNIQUE, ambassador_id TEXT, opened_at DATE,
            status TEXT DEFAULT 'active')"""),

    ("investment_funds", """
        CREATE TABLE IF NOT EXISTS investment_funds (
            fund_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, fund_type TEXT, manager_id TEXT,
            total_assets INTEGER DEFAULT 0, min_investment INTEGER,
            created_at DATE)"""),

    ("fund_holdings", """
        CREATE TABLE IF NOT EXISTS fund_holdings (
            holding_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER REFERENCES investment_funds(fund_id),
            investor_id TEXT, amount INTEGER, invested_at DATE)"""),

    ("exchange_rates", """
        CREATE TABLE IF NOT EXISTS exchange_rates (
            rate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency TEXT, rate REAL, updated_at DATETIME)"""),

    ("insurance_policies", """
        CREATE TABLE IF NOT EXISTS insurance_policies (
            policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, policy_type TEXT, premium INTEGER, coverage INTEGER,
            started_at DATE, status TEXT DEFAULT 'active')"""),

    ("insurance_claims", """
        CREATE TABLE IF NOT EXISTS insurance_claims (
            claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id INTEGER REFERENCES insurance_policies(policy_id),
            user_id TEXT, reason TEXT, amount_requested INTEGER,
            amount_paid INTEGER, status TEXT DEFAULT 'filed', filed_at DATE)"""),

    ("bankruptcies", """
        CREATE TABLE IF NOT EXISTS bankruptcies (
            case_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, total_debt INTEGER, total_assets INTEGER,
            status TEXT DEFAULT 'filed', filed_at DATE, closed_at DATE)"""),

    ("patents", """
        CREATE TABLE IF NOT EXISTS patents (
            patent_id INTEGER PRIMARY KEY AUTOINCREMENT,
            holder_id TEXT, invention TEXT, description TEXT,
            filed_at DATE, granted_at DATE, expires_at DATE,
            status TEXT DEFAULT 'pending')"""),

    ("properties", """
        CREATE TABLE IF NOT EXISTS properties (
            property_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT, property_type TEXT, location TEXT, value INTEGER,
            status TEXT DEFAULT 'owned', built_at DATE)"""),

    ("health_records", """
        CREATE TABLE IF NOT EXISTS health_records (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, condition TEXT, treatment TEXT, facility TEXT,
            date DATE, doctor_id TEXT)"""),

    ("universities", """
        CREATE TABLE IF NOT EXISTS universities (
            university_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, type TEXT, founded_at DATE)"""),

    ("courses", """
        CREATE TABLE IF NOT EXISTS courses (
            course_id INTEGER PRIMARY KEY AUTOINCREMENT,
            university_id INTEGER REFERENCES universities(university_id),
            name TEXT, professor_id TEXT, duration_weeks INTEGER)"""),

    ("student_records", """
        CREATE TABLE IF NOT EXISTS student_records (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT, course_id INTEGER REFERENCES courses(course_id),
            grade TEXT, completed_at DATE)"""),

    ("sports_teams", """
        CREATE TABLE IF NOT EXISTS sports_teams (
            team_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, sport TEXT, captain_id TEXT, created_at DATE)"""),

    ("sports_matches", """
        CREATE TABLE IF NOT EXISTS sports_matches (
            match_id INTEGER PRIMARY KEY AUTOINCREMENT,
            team1_id INTEGER REFERENCES sports_teams(team_id),
            team2_id INTEGER REFERENCES sports_teams(team_id),
            scheduled_at DATETIME, winner_id INTEGER)"""),

    ("marriages", """
        CREATE TABLE IF NOT EXISTS marriages (
            marriage_id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner1_id TEXT, partner2_id TEXT, married_at DATE,
            status TEXT DEFAULT 'active')"""),

    ("media_outlets", """
        CREATE TABLE IF NOT EXISTS media_outlets (
            outlet_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, media_type TEXT, owner_id TEXT,
            license_fee INTEGER, created_at DATE)"""),

    ("mail", """
        CREATE TABLE IF NOT EXISTS mail (
            mail_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT, recipient_id TEXT, message TEXT, item TEXT,
            sent_at DATETIME, delivered_at DATETIME)"""),

    ("environmental_reports", """
        CREATE TABLE IF NOT EXISTS environmental_reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id TEXT, location TEXT, pollution_type TEXT,
            severity TEXT, reported_at DATETIME, status TEXT DEFAULT 'open')"""),

    ("transport_routes", """
        CREATE TABLE IF NOT EXISTS transport_routes (
            route_id INTEGER PRIMARY KEY AUTOINCREMENT,
            transport_type TEXT, origin TEXT, destination TEXT,
            price INTEGER, status TEXT DEFAULT 'active')"""),

    ("transport_bookings", """
        CREATE TABLE IF NOT EXISTS transport_bookings (
            booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, route_id INTEGER REFERENCES transport_routes(route_id),
            class TEXT, booked_at DATETIME, status TEXT DEFAULT 'active')"""),

    ("farms", """
        CREATE TABLE IF NOT EXISTS farms (
            farm_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT, location TEXT, size INTEGER, created_at DATE)"""),

    ("crops", """
        CREATE TABLE IF NOT EXISTS crops (
            crop_id INTEGER PRIMARY KEY AUTOINCREMENT,
            farm_id INTEGER REFERENCES farms(farm_id),
            crop_type TEXT, quantity INTEGER, planted_at DATE, harvest_at DATE)"""),

    ("fishing_boats", """
        CREATE TABLE IF NOT EXISTS fishing_boats (
            boat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT, boat_type TEXT, capacity INTEGER, purchased_at DATE)"""),

    ("energy_plants", """
        CREATE TABLE IF NOT EXISTS energy_plants (
            plant_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT, plant_type TEXT, output INTEGER, location TEXT,
            built_at DATE)"""),

    ("telecom_towers", """
        CREATE TABLE IF NOT EXISTS telecom_towers (
            tower_id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT, coverage INTEGER, built_at DATE)"""),

    ("achievements", """
        CREATE TABLE IF NOT EXISTS achievements (
            achievement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, description TEXT, reward INTEGER,
            requirement TEXT)"""),

    ("player_achievements", """
        CREATE TABLE IF NOT EXISTS player_achievements (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            achievement_id INTEGER REFERENCES achievements(achievement_id),
            achieved_at DATE, claimed INTEGER DEFAULT 0,
            UNIQUE (user_id, achievement_id))"""),

    ("reputation", """
        CREATE TABLE IF NOT EXISTS reputation (
            user_id TEXT PRIMARY KEY,
            score INTEGER DEFAULT 0, last_updated DATE)"""),

    ("bounties", """
        CREATE TABLE IF NOT EXISTS bounties (
            bounty_id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id TEXT, placed_by TEXT, amount INTEGER, reason TEXT,
            status TEXT DEFAULT 'active', created_at DATE)"""),

    ("referrals", """
        CREATE TABLE IF NOT EXISTS referrals (
            referral_id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id TEXT, referee_id TEXT, rewarded INTEGER DEFAULT 0,
            created_at DATE)"""),

    ("seasonal_events", """
        CREATE TABLE IF NOT EXISTS seasonal_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, season TEXT, start_date DATE, end_date DATE, rewards TEXT)"""),

    ("comics", """
        CREATE TABLE IF NOT EXISTS comics (
            comic_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, issue_number INTEGER, content TEXT, published_at DATE)"""),

    ("backups", """
        CREATE TABLE IF NOT EXISTS backups (
            backup_id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_type TEXT, file_path TEXT, size INTEGER,
            created_at DATETIME, verified INTEGER DEFAULT 0)"""),

    ("system_logs", """
        CREATE TABLE IF NOT EXISTS system_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_type TEXT, message TEXT, severity TEXT, created_at DATETIME)"""),

    ("anti_cheat_flags", """
        CREATE TABLE IF NOT EXISTS anti_cheat_flags (
            flag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, flag_type TEXT, details TEXT,
            status TEXT DEFAULT 'open', flagged_at DATETIME)"""),
]


# ------------------------------------------------------------- cooldowns
# Upgrade, never recreate. `last_claimed DATE` is load-bearing for /daily and
# /weekly; `expires_at` is additive and carries the sub-minute cooldowns (F2).
async def upgrade_cooldowns(db: aiosqlite.Connection) -> list[str]:
    notes = []
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cooldowns'"
    ) as cur:
        exists = await cur.fetchone()

    if not exists:
        # Fresh database: database.py's init_db() creates the legacy shape, but
        # a brand-new file may not have it yet.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cooldowns (
                user_id TEXT, command TEXT, last_claimed DATE,
                expires_at DATETIME,
                PRIMARY KEY (user_id, command))""")
        notes.append("created cooldowns with expires_at")
        return notes

    async with db.execute("PRAGMA table_info(cooldowns)") as cur:
        columns = {row[1] for row in await cur.fetchall()}

    if "expires_at" in columns:
        notes.append("cooldowns.expires_at already present")
        return notes

    await db.execute("ALTER TABLE cooldowns ADD COLUMN expires_at DATETIME")
    # Legacy rows are day-granular claims; expire them at the end of that day so
    # they behave identically to how /daily and /weekly already treat them.
    await db.execute(
        "UPDATE cooldowns SET expires_at = last_claimed || ' 23:59:59' "
        "WHERE expires_at IS NULL AND last_claimed IS NOT NULL"
    )
    await db.execute(
        "UPDATE cooldowns SET expires_at = ? WHERE expires_at IS NULL",
        (datetime.now().isoformat(sep=" "),),
    )
    notes.append("added cooldowns.expires_at and backfilled existing rows")
    return notes


# ------------------------------------------------------- version tracking
async def ensure_version_table(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at DATETIME NOT NULL)""")


async def applied_versions(db: aiosqlite.Connection) -> set[str]:
    async with db.execute("SELECT version FROM schema_migrations") as cur:
        return {r[0] for r in await cur.fetchall()}


# --------------------------------------------------------------- migration
async def migration_001_expansion(db: aiosqlite.Connection) -> list[str]:
    """Create the expansion schema and upgrade the cooldowns table."""
    notes = []
    for name, ddl in NEW_TABLES:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ) as cur:
            already = await cur.fetchone()
        await db.execute(ddl)
        notes.append(f"{name}: {'existed' if already else 'created'}")
    notes.extend(await upgrade_cooldowns(db))
    return notes


MIGRATIONS = [("001_expansion", migration_001_expansion)]


# ----------------------------------------------------------- FK inspection
async def foreign_key_violations(db: aiosqlite.Connection) -> list[tuple]:
    """Rows that violate a declared FOREIGN KEY.

    Must be empty before turning on `PRAGMA foreign_keys`, otherwise existing
    writes start failing. Requires the pragma ON for `foreign_key_check` to be
    meaningful, so it is toggled for the duration of the check.
    """
    await db.execute("PRAGMA foreign_keys = ON")
    try:
        async with db.execute("PRAGMA foreign_key_check") as cur:
            return list(await cur.fetchall())
    finally:
        await db.execute("PRAGMA foreign_keys = OFF")


# --------------------------------------------------------------------- CLI
async def apply(db_path: str, dry_run: bool = False) -> int:
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await ensure_version_table(db)
        done = await applied_versions(db)

        pending = [(v, fn) for v, fn in MIGRATIONS if v not in done]
        if not pending:
            print(f"Nothing to do - all {len(MIGRATIONS)} migration(s) already applied.")
        for version, fn in pending:
            print(f"\n=== {version}{' (dry run)' if dry_run else ''} ===")
            if dry_run:
                print("  would run")
                continue
            notes = await fn(db)
            for note in notes:
                print(f"  {note}")
            await db.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now().isoformat(sep=" ")),
            )
            await db.commit()
            print(f"  recorded {version}")

        violations = await foreign_key_violations(db)
        print(f"\nForeign key violations: {len(violations)}")
        for row in violations[:10]:
            print(f"  {row}")
        if violations:
            print("  Resolve these before relying on FK enforcement.")
    return 0


async def status(db_path: str) -> int:
    if not os.path.exists(db_path):
        print(f"{db_path} does not exist yet.")
        return 0
    async with aiosqlite.connect(db_path) as db:
        await ensure_version_table(db)
        await db.commit()
        done = await applied_versions(db)
        for version, _ in MIGRATIONS:
            print(f"  {'applied' if version in done else 'pending':>8}  {version}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Dravia State Bot migrations")
    parser.add_argument("--database", default=DATABASE_PATH, help="path to the SQLite file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="report without changing anything")
    group.add_argument("--status", action="store_true", help="list applied/pending migrations")
    args = parser.parse_args()

    if args.status:
        return asyncio.run(status(args.database))
    return asyncio.run(apply(args.database, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())