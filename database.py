"""Dravia State Bot - Database Setup & Models"""
import aiosqlite
import os
import sqlite3
from datetime import datetime, date, timedelta

from utils.logger import bot_log

# Keep in sync with config.py / .env.example: every cog resolves its own
# Database(DATABASE_PATH) with this same default, and Database() below uses it
# as the fallback argument.
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/dravia.db")

# Set once if the expansion migration has not been applied yet.
_WARNED_MISSING_EXPIRES_AT = False


def _fk_connector(db_path: str):
    """Build a zero-arg connector that enables foreign key enforcement.

    `aiosqlite.connect()` builds its own internal connector and does not accept
    one, so `aiosqlite.Connection` is constructed directly instead. The pragma
    must be set at creation: SQLite treats `foreign_keys` as a no-op inside a
    transaction, so it cannot be applied once queries have begun.
    """
    def connector() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    return connector

async def init_db():
    """Initialize the database with all tables."""
    os.makedirs(os.path.dirname(DATABASE_PATH) if os.path.dirname(DATABASE_PATH) else "data", exist_ok=True)
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        # Users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                balance INTEGER DEFAULT 500,
                total_earned INTEGER DEFAULT 0,
                total_spent INTEGER DEFAULT 0,
                tax_paid INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                last_active DATE,
                is_citizen INTEGER DEFAULT 0,
                citizenship_date DATE,
                created_at DATE DEFAULT CURRENT_DATE
            )
        """)
        
        # Transactions log
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user TEXT,
                to_user TEXT,
                amount INTEGER,
                type TEXT,
                description TEXT,
                created_at DATE DEFAULT CURRENT_DATE,
                created_time TIME DEFAULT CURRENT_TIME
            )
        """)
        
        # Cooldowns for daily/weekly claims
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cooldowns (
                user_id TEXT,
                command TEXT,
                last_claimed DATE,
                PRIMARY KEY (user_id, command)
            )
        """)
        
        # Citizen IDs
        await db.execute("""
            CREATE TABLE IF NOT EXISTS citizens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT UNIQUE NOT NULL,
                citizen_id TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                date_of_birth TEXT NOT NULL,
                nationality TEXT DEFAULT 'Dravian',
                rank TEXT DEFAULT 'Citizen',
                issued_at TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                avatar_url TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        # Grants
        await db.execute("""
            CREATE TABLE IF NOT EXISTS grants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                program_name TEXT NOT NULL,
                amount INTEGER NOT NULL,
                claimed_at TEXT NOT NULL
            )
        """)
        
        # Bank accounts
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bank_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                savings INTEGER DEFAULT 0,
                loan_balance INTEGER DEFAULT 0,
                loan_term INTEGER DEFAULT 0,
                loan_start TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Civil service
        await db.execute("""
            CREATE TABLE IF NOT EXISTS civil_servants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                grade TEXT NOT NULL,
                job_family TEXT NOT NULL,
                hire_date TEXT,
                status TEXT DEFAULT 'active',
                probation_until TEXT,
                pension_years REAL DEFAULT 0
            )
        """)
        
        # Police
        await db.execute("""
            CREATE TABLE IF NOT EXISTS police (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                rank TEXT,
                join_date TEXT,
                status TEXT DEFAULT 'active',
                arrests INTEGER DEFAULT 0
            )
        """)
        
        # Criminals
        await db.execute("""
            CREATE TABLE IF NOT EXISTS criminals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT UNIQUE NOT NULL,
                offense_count INTEGER DEFAULT 0,
                fines_due INTEGER DEFAULT 0,
                jail_days INTEGER DEFAULT 0,
                last_arrest TEXT
            )
        """)
        
        # Stock portfolio
        await db.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                user_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                shares INTEGER DEFAULT 0,
                avg_price INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, symbol)
            )
        """)
        
        # Warrants
        await db.execute("""
            CREATE TABLE IF NOT EXISTS criminal_records (
                record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                charge TEXT,
                severity TEXT,
                fine INTEGER DEFAULT 0,
                jail_days INTEGER DEFAULT 0,
                date TEXT,
                officer_id TEXT,
                case_status TEXT DEFAULT 'open'
            )
        """)
        
        # Warrants
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warrants (
                warrant_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                reason TEXT,
                issued_by TEXT,
                date TEXT,
                status TEXT DEFAULT 'active'
            )
        """)
        
        # BOLOs (Be On the Look Out)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bolos (
                bolo_id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT,
                issued_by TEXT,
                date TEXT,
                status TEXT DEFAULT 'active'
            )
        """)
        
        # Police duty sessions
        await db.execute("""
            CREATE TABLE IF NOT EXISTS duty_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT
            )
        """)
        
        # Internal Affairs complaints / investigations
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ia_cases (
                case_id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id TEXT,
                complainant_id TEXT,
                reason TEXT,
                status TEXT DEFAULT 'open',
                findings TEXT,
                penalty TEXT,
                opened_at TEXT,
                closed_at TEXT
            )
        """)
        
        # Police Academy applications & training
        await db.execute("""
            CREATE TABLE IF NOT EXISTS academy (
                user_id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'applicant',
                exam_score INTEGER,
                modules_done TEXT DEFAULT '',
                written_test INTEGER DEFAULT 0,
                practical_test INTEGER DEFAULT 0,
                firearms_test INTEGER DEFAULT 0,
                graduated_at TEXT,
                applied_at TEXT
            )
        """)
        
        # Taxes (weekly assessments)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS taxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                tax_type TEXT,
                amount INTEGER,
                week_start TEXT,
                paid INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)
        
        # Houses
        await db.execute("""
            CREATE TABLE IF NOT EXISTS houses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                house_name TEXT,
                channel_id TEXT,
                guests TEXT DEFAULT '',
                rental_due TEXT,
                last_activity TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        # Gambling limits & stats
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gambling_limits (
                user_id TEXT PRIMARY KEY,
                daily_deposit_limit INTEGER DEFAULT 500,
                daily_loss_limit INTEGER DEFAULT 200,
                daily_loss_used INTEGER DEFAULT 0,
                daily_wagered INTEGER DEFAULT 0,
                loss_date TEXT,
                self_excluded_until TEXT
            )
        """)
        
        # Lottery tickets
        await db.execute("""
            CREATE TABLE IF NOT EXISTS lottery_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                numbers TEXT,
                draw_date TEXT,
                won INTEGER DEFAULT 0
            )
        """)
        
        # Businesses
        await db.execute("""
            CREATE TABLE IF NOT EXISTS businesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                owner_id TEXT NOT NULL,
                business_type TEXT,
                license_type TEXT,
                description TEXT,
                registered_at TEXT,
                is_active INTEGER DEFAULT 1,
                monthly_renewal_due TEXT,
                facility_tier INTEGER DEFAULT 0,
                daily_points INTEGER DEFAULT 0,
                specialization TEXT
            )
        """)
        
        # Business employees
        await db.execute("""
            CREATE TABLE IF NOT EXISTS business_employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT,
                salary INTEGER DEFAULT 0,
                hired_at TEXT
            )
        """)
        
        # Business inventory
        await db.execute("""
            CREATE TABLE IF NOT EXISTS business_inventory (
                business_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                point_value INTEGER DEFAULT 1,
                PRIMARY KEY (business_id, product_name)
            )
        """)
        
        # Mining concessions
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mining_concessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER,
                owner_id TEXT,
                concession_type TEXT,
                location TEXT,
                tier INTEGER DEFAULT 0,
                daily_points INTEGER DEFAULT 0,
                royalty_rate REAL DEFAULT 0.0,
                rehabilitation_bond INTEGER DEFAULT 0,
                minerals TEXT DEFAULT '',
                granted_at TEXT,
                expires_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        # Customs declarations
        await db.execute("""
            CREATE TABLE IF NOT EXISTS customs_declarations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                declaration_type TEXT,
                goods TEXT,
                value INTEGER,
                origin TEXT,
                duty_paid INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                filed_at TEXT
            )
        """)
        
        # AEO traders
        await db.execute("""
            CREATE TABLE IF NOT EXISTS aeo_traders (
                user_id TEXT PRIMARY KEY,
                approved_at TEXT
            )
        """)
        
        # Consumer complaints
        await db.execute("""
            CREATE TABLE IF NOT EXISTS consumer_complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complainant_id TEXT NOT NULL,
                trader_id TEXT,
                reason TEXT,
                status TEXT DEFAULT 'open',
                filed_at TEXT,
                resolved_at TEXT,
                outcome TEXT
            )
        """)
        
        # Events
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                event_type TEXT,
                organizer_id TEXT,
                date TEXT,
                location TEXT,
                ticket_price INTEGER DEFAULT 0,
                funding INTEGER DEFAULT 0,
                status TEXT DEFAULT 'proposed'
            )
        """)
        
        # Event registrations (attendees, sponsors, vendors)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS event_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                kind TEXT DEFAULT 'attendee',
                amount INTEGER DEFAULT 0
            )
        """)
        
        # Laws (Curia)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS laws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                law_name TEXT,
                law_text TEXT,
                proposed_by TEXT,
                proposed_at TEXT,
                votes_yes INTEGER DEFAULT 0,
                votes_no INTEGER DEFAULT 0,
                votes_abstain INTEGER DEFAULT 0,
                status TEXT DEFAULT 'proposed',
                enacted_at TEXT
            )
        """)
        
        # Law votes (one per user per law)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS law_votes (
                law_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                vote TEXT,
                PRIMARY KEY (law_id, user_id)
            )
        """)
        
        # News / Gazette articles
        await db.execute("""
            CREATE TABLE IF NOT EXISTS news_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                content TEXT,
                author_id TEXT,
                kind TEXT DEFAULT 'news',
                published_at TEXT
            )
        """)
        
        # Lore Academy enrolments
        await db.execute("""
            CREATE TABLE IF NOT EXISTS academy_enrolments (
                user_id TEXT PRIMARY KEY,
                enrolled_at TEXT,
                scholarship INTEGER DEFAULT 0,
                quizzes_done INTEGER DEFAULT 0,
                perfect_scores INTEGER DEFAULT 0,
                graduated INTEGER DEFAULT 0
            )
        """)
        
        # Alt-account detection flags
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alt_flags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                reason TEXT,
                flagged_at TEXT
            )
        """)
        
        await db.commit()
        from utils.logger import bot_log
        bot_log.info("Database initialized")


class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
    
    async def get_connection(self):
        # Return an un-started Connection; the caller's `async with await ...`
        # starts the worker thread exactly once (aiosqlite >= 0.21 raises if started twice).
        return aiosqlite.Connection(_fk_connector(self.db_path), 64)
    
    # User operations
    async def get_user(self, user_id: str):
        async with await self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),)) as cursor:
                return await cursor.fetchone()
    
    async def create_user(self, user_id: str, balance: int = 500):
        async with await self.get_connection() as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance, created_at) VALUES (?, ?, ?)",
                (str(user_id), balance, date.today().isoformat())
            )
            await db.commit()
    
    async def get_balance(self, user_id: str) -> int:
        user = await self.get_user(user_id)
        return user["balance"] if user else 0
    
    async def add_balance(self, user_id: str, amount: int, transaction_type: str = "deposit", description: str = ""):
        async with await self.get_connection() as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (str(user_id),))
            await db.execute(
                "UPDATE users SET balance = balance + ?, total_earned = total_earned + ? WHERE user_id = ?",
                (amount, amount, str(user_id))
            )
            await db.execute(
                "INSERT INTO transactions (from_user, to_user, amount, type, description) VALUES (?, ?, ?, ?, ?)",
                ("system", str(user_id), amount, transaction_type, description)
            )
            await db.commit()
    
    async def remove_balance(self, user_id: str, amount: int, transaction_type: str = "withdrawal", description: str = ""):
        async with await self.get_connection() as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (str(user_id),))
            await db.execute(
                "UPDATE users SET balance = balance - ?, total_spent = total_spent + ? WHERE user_id = ?",
                (amount, amount, str(user_id))
            )
            await db.execute(
                "INSERT INTO transactions (from_user, to_user, amount, type, description) VALUES (?, ?, ?, ?, ?)",
                (str(user_id), "system", amount, transaction_type, description)
            )
            await db.commit()
    
    async def transfer(self, from_id: str, to_id: str, amount: int, description: str = ""):
        async with await self.get_connection() as db:
            # Ensure both accounts exist so funds can never vanish
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (str(from_id),))
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (str(to_id),))
            await db.execute(
                "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                (amount, str(from_id))
            )
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (amount, str(to_id))
            )
            await db.execute(
                "INSERT INTO transactions (from_user, to_user, amount, type, description) VALUES (?, ?, ?, ?, ?)",
                (str(from_id), str(to_id), amount, "transfer", description)
            )
            await db.commit()
    
    # Cooldown operations
    async def get_cooldown(self, user_id: str, command: str) -> str:
        async with await self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT last_claimed FROM cooldowns WHERE user_id = ? AND command = ?",
                (str(user_id), command)
            ) as cursor:
                row = await cursor.fetchone()
                return row["last_claimed"] if row else None

    async def set_cooldown(self, user_id: str, command: str, expires_at: str | None = None):
        """Record a claim.

        Day-granular callers (economy `/daily`, `/weekly`) pass nothing and get
        today's date in `last_claimed`, exactly as before. Passing `expires_at`
        additionally stamps the sub-minute cooldown column added by migrate.py.
        """
        async with await self.get_connection() as db:
            try:
                await db.execute(
                    "INSERT OR REPLACE INTO cooldowns (user_id, command, last_claimed, expires_at) "
                    "VALUES (?, ?, ?, ?)",
                    (str(user_id), command, date.today().isoformat(), expires_at)
                )
            except sqlite3.OperationalError as exc:
                if "expires_at" not in str(exc):
                    raise
                # Migration 001 has not been applied yet. Fall back so the
                # economy keeps working, and complain once.
                global _WARNED_MISSING_EXPIRES_AT
                if not _WARNED_MISSING_EXPIRES_AT:
                    _WARNED_MISSING_EXPIRES_AT = True
                    bot_log.warning(
                        "cooldowns.expires_at is missing - run `python migrate.py`. "
                        "Second-based cooldowns are disabled until then."
                    )
                await db.execute(
                    "INSERT OR REPLACE INTO cooldowns (user_id, command, last_claimed) VALUES (?, ?, ?)",
                    (str(user_id), command, date.today().isoformat())
                )
            await db.commit()

    async def set_expiring_cooldown(self, user_id: str, command: str, seconds: float):
        """Start a cooldown that expires in `seconds` (system F2).

        Returns False when the migration is not applied, so callers can decide
        whether to enforce the cooldown or carry on.
        """
        expires = (datetime.now() + timedelta(seconds=seconds)).isoformat(sep=" ", timespec="seconds")
        async with await self.get_connection() as db:
            try:
                await db.execute(
                    "INSERT OR REPLACE INTO cooldowns (user_id, command, last_claimed, expires_at) "
                    "VALUES (?, ?, ?, ?)",
                    (str(user_id), command, date.today().isoformat(), expires)
                )
            except sqlite3.OperationalError as exc:
                if "expires_at" not in str(exc):
                    raise
                return False
            await db.commit()
        return True

    async def cooldown_remaining(self, user_id: str, command: str) -> float:
        """Seconds left on an expiring cooldown, or 0.0 when free/unavailable."""
        async with await self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            try:
                async with db.execute(
                    "SELECT expires_at FROM cooldowns WHERE user_id = ? AND command = ?",
                    (str(user_id), command)
                ) as cursor:
                    row = await cursor.fetchone()
            except sqlite3.OperationalError as exc:
                if "expires_at" not in str(exc):
                    raise
                return 0.0
        if not row or not row["expires_at"]:
            return 0.0
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            return 0.0
        remaining = (expires - datetime.now()).total_seconds()
        return max(0.0, remaining)
    
    # Leaderboard
    async def get_leaderboard(self, limit: int = 10):
        async with await self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,)
            ) as cursor:
                return await cursor.fetchall()
    
    # Economy stats
    async def get_economy_stats(self):
        async with await self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT COUNT(*) as total_users, SUM(balance) as total_money, AVG(balance) as avg_balance FROM users"
            ) as cursor:
                return await cursor.fetchone()
    
    # Transaction history
    async def get_transactions(self, user_id: str, limit: int = 10):
        async with await self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM transactions WHERE from_user = ? OR to_user = ? ORDER BY id DESC LIMIT ?",
                (str(user_id), str(user_id), limit)
            ) as cursor:
                return await cursor.fetchall()