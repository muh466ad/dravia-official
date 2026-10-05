# Dravia State Bot

A complete, production-ready Discord bot for the **Republic of Dravia** — implementing the nation's economy, civil service, police, banking, business, mining, stock market, taxes, housing, gambling, customs, consumer protection, grants, events, legislature, lore and news systems.

## Quick Start

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your Discord token
```

3. **Run the bot:**
```bash
python bot.py
```

4. **In your server:** run `/setup` (creates roles & channels), then `/help` and `/status`.

### Docker

```bash
cp .env.example .env   # fill in DISCORD_TOKEN
docker compose up -d --build
```

## Hosting on Wispbyte (or any Pterodactyl panel)

Wispbyte and most game-server panels run each server inside a prebuilt Docker image.
You do **not** build your own image there — the `Dockerfile` above is only for local/VPS use.

**1. Docker image** — pick `Python 3.11` or `3.12` when creating the server.
`discord.py` 2.x needs 3.8+, but the code uses modern syntax, so avoid 3.8/3.9.

**2. Upload the code** — use the panel's File Manager and upload the project
directory (`bot.py`, `cogs/`, `utils/`, `config.py`, `database.py`, `scheduler.py`,
`requirements.txt`). Keep the folder structure intact; cogs are imported as `cogs.<name>`.

**3. Startup command** (Startup tab):
```
python bot.py
```
Pterodactyl installs from `requirements.txt` before running this, so leave
**Additional Python Packages** empty.

**4. Environment variables** (Startup tab):

| Variable | Value | Required |
|---|---|---|
| `DISCORD_TOKEN` | Your bot token from the Developer Portal | Yes |
| `OWNER_ID` | Your numeric Discord user ID | Yes |
| `DATABASE_PATH` | `data/dravia.db` | No (default) |
| `LOG_DIR` | `logs` | No (default) |

Set these in the panel rather than uploading a `.env` — `load_dotenv()` does not
override real environment variables, so panel values win.

Leave `DEV_GUILD_ID` **unset** in production. When it is set, commands sync to that
one guild immediately; without it, Discord propagates the global sync over up to an hour.

**5. Enable privileged intents** — in the Discord Developer Portal (Bot → Privileged
Gateway Intents) turn on **Presence**, **Server Members**, and **Message Content**.
`bot.py` requests `members` and `message_content`; without them the bot logs in but
every command that reads member data fails at runtime.

**6. Start and verify** — Console tab → Start. Look for `✅ Bot fully initialized and ready!`.
Then run `/setup` in your server to create the roles and channels.

### Notes for panel hosting

- **One bot per server.** Wispbyte's free tier allows a single Discord bot per server.
- **Ports go unused.** A Discord bot makes an outbound connection and never listens,
  so any allocation the panel requires (`node:port`) stays idle. That's expected.
- **Persistence.** The SQLite file at `data/dravia.db` and `logs/` live inside the server
  directory and survive restarts. There are no off-node backups — use the panel's backup
  feature if it offers one, especially before large schema changes.
- **Deployment is SQLite-only.** The schema is PostgreSQL-compatible, but `database.py`
  connects with `aiosqlite` and nothing reads a connection URL. See *Database backend* below.

### Deploying from GitHub

Pterodactyl has **no built-in Git integration** — cloning a repo from a startup command
is the portable approach (a few hosts ship a custom "egg" that adds a Git tab; check
Startup first, and use this method if there isn't one).

**1. Push the repo** — from your machine (this repo's branch is `master`):
```bash
git remote add origin https://github.com/<you>/dravia-state-bot.git
git push -u origin master
```
`.gitignore` already excludes `.env`, `data/` and `logs/`, so your bot token and live
database never reach GitHub.

**2. Startup command** — clone on first boot, then pull. This one command works for both
cases, so you don't have to change it later:
```
bash -c "cd /home/container && { [ -d dravia/.git ] || git clone --depth 1 https://github.com/<you>/dravia-state-bot.git dravia; } && cd dravia && git pull --ff-only && pip install -q -r requirements.txt && python bot.py"
```
The `[ -d dravia/.git ] ||` guard is what makes it idempotent. A bare `git clone` into an
existing directory prints `fatal: destination path already exists` but **still exits 0**,
so a plain `&&` chain would silently keep running yesterday's code.

**3. Updating** — just restart the server. `git pull` picks up new commits.

Notes:
- **`/home/container`** is the usual Pterodactyl server directory. If your panel uses a
  different path, check it in the File Manager before pasting.
- **Private repos** need a token. Put it in a panel env var and reference it as
  `https://$GITHUB_TOKEN@github.com/<you>/<repo>.git` — never paste the token into the
  startup command itself, since the panel shows it on screen and in logs. Note that
  `$GITHUB_TOKEN` is expanded by the shell, so it won't be visible in the command field.
- **Keep your database outside the cloned tree** so updates never touch your data. Set
  `DATABASE_PATH=/home/container/dravia-data/dravia.db` in the panel env vars, and create
  that folder in the File Manager once. Leaving it at `data/dravia.db` puts it *inside*
  the repo, where a fresh clone would wipe it.

### Database backend

SQLite via `aiosqlite` is the only implemented backend. It handles a single bot instance
fine. Migrating to PostgreSQL is a real piece of work, not a config change — the query layer
uses `?` placeholders, `INSERT OR IGNORE/REPLACE`, `cursor.lastrowid`, and positional
`row[0]` indexing, none of which map cleanly onto `asyncpg`. It needs a deliberate
per-table migration against a live database.

## Command Overview (325 slash commands)

Commands are grouped (e.g. `/police duty_start`) to fit Discord's 100-command limit.
Run `/help category:...` in Discord for details per category.

### 💰 Economy
- `/balance` `/pay` `/daily` (50 Ovi) `/weekly` (350 Ovi, Sunday) `/leaderboard` `/economy`
- `/bank balance|deposit|withdraw|loan|repay` — savings, loans, 10,000 Ovi deposit insurance
- `/tax check|declare|pay|history|wealth|estimate` — progressive income & wealth tax
- `/tax audit|assess|penalty|cross_reference|hnwi|publish` — Revenue Office (Revenue Staff role)
- `/fund create|list|info|invest|redeem|portfolio|rates|rate` — investment funds & FX (Fund Manager)
- `/insurance buy|policies|claim|claims|approve|deny|cancel|bankrupt|cases|settle` — cover, claims, insolvency
- `/referral code|claim|board` — 500 Ovi to the referrer, 250 to the referee

### 🏛️ Government
- `/apply` `/myid` `/lookup` `/citizens` `/setrank` — citizenship & ID cards
- `/civilservice apply|status|salary|list|approve|promote|dismiss` — Grades A–G, 10 job families
- `/curia propose|vote|status|debate|summon|committee|report|register` — legislature
- `/audit police|economy|business|government|citizen` — Curial oversight (Curial role)
- `/grant` `/grants` — Cygnus Decree programmes (1.6M Ovi budget)
- `/news publish|list|latest` `/gazette announce|budget|production|enforcement|economic`
- `/lore flag|characters|history|timeline|constitution|comic`
- `/immigration apply|status|mine|pending|approve|deny|revoke` — visas (Immigration Officer)
- `/diplomacy open|close|appoint|recall|info|list|policy` — embassies (Diplomat)
- `/education found|universities|offer|courses|enroll|transcript|grade|drop` — universities (Professor)
- `/patent file|info|mine|pending|grant|reject|renew|search` — patents (Patent Officer)
- `/mail send|inbox|read` `/marriage marry|divorce|status` `/reputation`
- `/setup` `/admin pay|set_balance|log|roles` `/admin backup|backups|flag|flags|flag_close|syslog|logs`

### 👮 Police (De Custodia Publica Draviae)
- `/police join|record|wanted|duty_start|duty_end|status|miranda|cuff|uncuff|search|jail|release`
- `/police warrant_issue|warrant_serve|warrant_list|bolo_create|bolo_list|report|radio`
- `/arrest` `/pay_fine`
- `/ia complaint|investigate|findings|penalty|register` — Internal Affairs
- `/ipoc review|adopt_or_explain|investigate|report|mediation` — independent oversight
- `/academy apply|exam|train|test|status|graduate|oath` — Police Academy
- `/fire report|dispatch|resolve|status|log|history|stations` — Fire Service
- `/military recruit|enlist|roster|status|deploy|drill|disband` — Defence Forces
- `/intel brief|list|status|complete|compromise|declassify` — State Security Service
- `/bounty post|list|claim|retract` — the bounty board

### 🏢 Commerce
- `/business register|list|info|renew|close|hire|fire|employees|report`
- `/facility build|upgrade|status` `/produce` `/inventory` — production & specialization bonuses
- `/mine claim|build|produce|refine|status|safety|bond|close` — concessions, royalties, refining
- `/stock list|buy|sell|portfolio` — Chrysanthemum Securities Exchange
- `/customs import|export|permit|transhipment|status|rates|inspect|approve|seize|audit|aeo_apply|aeo_list`
- `/consumer rights|complaint|status|refund|recall|tribunal|investigate|order|fine|recall_order`
- `/event propose|list|register|sponsor|vendor|report|calendar`
- `/season announce|list|current|upcoming` — seasonal calendar (Minister announces)
- `/property buy|sell|list|info|upgrade|deed|market` — Land Registry
- `/media found|outlets|info|transfer|comic|comics|read` — outlets & comics (Media Owner)
- `/farm claim|plant|status|harvest|list|sell` `/fishing buy|fish|fleet|sell` — agriculture
- `/env report|open|resolve|stats` — pollution reports (Minister resolves)
- `/transport route|list|book|tickets` `/utility power|telecom|plants|towers` — state infrastructure (Minister opens routes)

### 🎮 Society
- `/casino slots|blackjack|roulette|dice|crash|limits|self_exclude|stats` — State casino, player protection
- `/lottery buy|draw|jackpot`
- `/house apply|invite|remove|renew|cancel|info` — private channel per house
- `/achievements list|mine|claim|progress`
- `/health checkup|treat|history|records|vitals|clinic` — health records (Doctor treats)
- `/sports team|teams|info|challenge|result|fixtures|standings` — clubs & fixtures (Tournament Organiser records results)

### Utility
- `/help [category]` — categorized help
- `/status` — system health (uptime, cogs, scheduler, DB)
- `/setup` — creates all roles & channels from the Permissions Matrix

## Scheduled Tasks (APScheduler)

| When | Task |
|---|---|
| Daily 00:00 | Reset gambling/daily limits |
| Daily 09:00 / 18:00 | Morning / evening news summary |
| Sunday 00:00 | Pay salaries (civil service, police, employees) |
| Sunday 09:00 | Weekly UBI (350 Ovi to all citizens) |
| Sunday 12:00 | Withhold outstanding taxes |
| Sunday 18:00 | Weekly production report |
| 1st of month 00:30 | Business renewals & house rents (defaults closed) |
| 1st of month 09:00 | Monthly budget report |
| 15th 09:00 | Wealth tax assessments |
| Quarterly | Economic report & law review |

## Configuration (.env)

```
DISCORD_TOKEN=your_bot_token_here
DATABASE_PATH=data/dravia.db
OWNER_ID=your_discord_id
DEV_GUILD_ID=optional_guild_id_for_testing
LOG_DIR=logs
```

## Logging

Rotating UTF-8 logs in `logs/`: `bot.log`, `transactions.log`, `police.log`, `audit.log`, `errors.log`, `admin.log`.

## Database Migrations

Schema changes ship as numbered, idempotent migrations. **Run this after pulling
changes and before restarting the bot**, otherwise the new systems will fail:

```
python migrate.py --status     # see what is pending
python migrate.py --dry-run    # preview without touching anything
python migrate.py              # apply
```

Applied versions are tracked in `schema_migrations`, so re-running is safe.
**The bot also applies pending migrations at startup** (after `init_db()`), so a
fresh deployment works without a manual step — `migrate.py` stays useful for
previewing (`--dry-run`) and auditing (`--status`) what will run.

Migration `001_expansion` adds 40 tables (military, intelligence, fire, visas,
embassies, funds, exchange rates, insurance, bankruptcies, patents, property,
health, education, sports, marriages, media, mail, environment, transport,
farms, fishing, energy, telecom, achievements, reputation, bounties, referrals,
seasonal events, comics, backups, system logs and anti-cheat flags).

Two things worth knowing:

- **`cooldowns` is upgraded in place, never recreated.** It already existed with
  `last_claimed DATE`, which `/daily` and `/weekly` compare against today's date.
  The migration `ALTER`s it to add an `expires_at` column for the sub-minute
  cooldowns and backfills existing rows, preserving all claim history. Until you
  run it, second-based cooldowns are unavailable and the bot logs a warning.
- **Foreign keys are now enforced.** SQLite ignores `FOREIGN KEY` clauses
  unless `PRAGMA foreign_keys = ON`, which `Database.get_connection()` sets on
  every connection. The migration reports any pre-existing violations before
  switching enforcement on.

## The Dravian Calendar

The Republic keeps its own era. Real dates are shifted by a constant offset so that
"today" falls in **1985**, and every public record — Gazette, news archive, citizen IDs,
enacted laws, rent and concession deadlines — agrees with `/lore timeline`.

Configure with two optional environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `DRAVIA_CURRENT_YEAR` | `1985` | The in-world year matching the real current year |
| `DRAVIA_FOUNDED_YEAR` | `1953` | Founding of the Republic; frames the timeline |

The offset is derived from the real current year, so the in-world calendar advances
day by day and rolls into 1986 after the same span of real time. The timeline events
themselves are a plain list in `cogs/lore.py` (`TIMELINE`) and are safe to edit.

Dates in SQLite stay in real-world ISO format — only the *display* is converted, so
no migration is needed.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

The suite guards the failure modes that are invisible until they bite: `/setup` staying in
sync with the roles in `utils/checks.py`, the Permissions Matrix, an audit that no
command may await Discord API calls before answering its interaction (Discord expires
those after 3 seconds), the expansion migration's idempotency and its preservation of
`cooldowns` history, and the Discord embed limits that turn long player input into
HTTP 400s.

## Project Structure

```
/dravia-state-bot
  bot.py             # Entry point, /help, /status, error handling
  config.py          # Configuration from .env
  database.py        # Schema (34 tables) + Database model layer
  scheduler.py       # APScheduler jobs (daily/weekly/monthly/quarterly)
  requirements.txt
  .env.example
  Dockerfile / docker-compose.yml
  /cogs
    economy.py  citizenship.py  grants.py  banking.py  civil_service.py
    police.py  police_academy.py  stock_market.py  taxes.py  housing.py
    business.py  mining.py  gambling.py  customs.py  consumer_protection.py
    events.py  curia.py  lore.py  news.py  admin.py  achievements.py
    military.py  intelligence.py  fire.py  immigration.py  diplomacy.py
    health.py  education.py  funds.py  insurance.py  patents.py  property.py
    sports.py  media.py  agriculture.py
  /utils
    checks.py  formatters.py  validators.py  logger.py
  /data/dravia.db     # SQLite (auto-created)
  /logs/              # Rotating logs (auto-created)
```

## Tech Stack

- Python 3.11+
- discord.py 2.x (slash commands)
- aiosqlite (async SQLite)
- APScheduler (national scheduled tasks)
- python-dotenv

## Permissions Matrix (created by `/setup`)

@everyone: economy, grants, housing, consumer complaints ·
@Citizen: voting, UBI · @Police Officer: police commands · @Sergeant+: supervisors ·
@Bank Staff: loans · @Revenue Staff: tax enforcement · @SEC: investigations ·
@Consumer Protection: consumer authority · @Curial: curia & audits ·
@Minister: departmental commands · @Admin: full access

## Colors

- Crimson: `#8B0000` · Gold: `#D4AF37` · Black: `#1A1A1A`

---
*For the glory of Dravia! 🇩🇷*
