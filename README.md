# Sports Data Scraper

Multi-sport data aggregation system that scrapes **FlashScore.com** using Selenium and stores data in PostgreSQL. Covers Football, Basketball, Baseball, Hockey, American Football, Tennis, Golf, and Boxing — collecting leagues, teams, matches, fixtures, news, and player data.

---

## Architecture

![Arquitectura y Flujo del Sistema](git_images/Arquitectura%20y%20flujo.png)

```
├── main.py                  # Entry point — launches 2 concurrent threads
├── main1.py                 # Scheduled scraping (news, leagues, teams, results, fixtures, players)
├── main2.py                 # Live match score updates
├── main_manual_adjust.py    # Manual one-off execution with flags
├── paralel_execution.py     # Parallel extraction across N browser sessions
│
├── src/                     # Core modules
│   ├── common_functions.py  # Selenium utilities, login, file I/O, scheduling
│   ├── data_base.py         # All PostgreSQL operations (50+ CRUD functions)
│   ├── milestone1.py        # News extraction
│   ├── milestone2.py        # Sport records and league data
│   ├── milestone3.py        # Teams creation
│   ├── milestone4.py        # Results and fixtures extraction
│   ├── milestone6.py        # Player data
│   ├── milestone7.py        # Live scores (support)
│   ├── milestone8.py        # Live score updates
│   └── extract_football_match.py  # Football-specific match extraction
│
├── scripts/                 # Utilities and maintenance
│   ├── db_status.py         # Show full DB summary table
│   ├── check_teams_db.py    # Sync teams_report.json with DB counts
│   ├── rebuild_leagues_season.py  # Rebuild leagues_season/ files from DB
│   ├── connect_driver.py    # Reconnect to active Selenium session
│   ├── clean_all.py         # Reset all checkpoints and clear DB
│   ├── stop_process.py      # Kill browser/driver processes
│   ├── update_repo.py       # Pull latest changes from remote
│   ├── update_server.py     # Deploy to remote server
│   ├── migrate_leagues_info.py    # Migrate leagues_info.json schema
│   ├── get_last_changes.py        # Show recent DB changes
│   ├── test_boxing_extraction.py  # End-to-end test for extract_info_boxing()
│   ├── test_f1_extraction.py      # End-to-end test for create_events_f1()
│   ├── debug_f1.py                # F1 page selector inspection
│   └── debug_golf_player_profile.py  # Golf player profile selector inspection
│
├── tests/                   # Test scripts
│   ├── test.py
│   ├── test_login.py
│   └── test_url.py
│
├── notebooks/               # Interactive debugging
│   └── main_depuracion.ipynb
│
├── check_points/            # Runtime state (JSON checkpoints)
├── api_service/             # FastAPI stub
├── postgress_init/          # PostgreSQL initialization scripts
└── logs/                    # Execution logs
```

---

## Module Flow

### milestone3 — Teams creation

```
leagues_info.json
    │
    ▼ per sport/league with teams_creation.extract = true
    ├─ [RESUME] reads last_team_created → skips already-processed teams
    ├─ navigates to league standings or draw page
    ├─ get_teams_info_part1() → scrapes team table (name, position, URL, stats)
    ├─ per team:
    │    ├─ navigates to team URL
    │    ├─ get_teams_info_part2() → extracts name, country, stadium, logo
    │    ├─ create_team_in_db() → looks up local cache → inserts if not found
    │    └─ checkpoint: saves last_team_created in leagues_info.json
    └─ on league complete: status='completed', last_team_created=''
```

<!-- RISKS (milestone3):
  - Classic CSS selectors (tableCellParticipant, tableCellRank, table__cell--form) may break
    if FlashScore migrates to wcl-* classes (already done for news in milestone1).
  - get_teams_info_part1() silently catches header errors with bare except: print("--")
    which hides failures without propagating them.
-->

---

### milestone4 — Results & Fixtures extraction

```
leagues_info.json
    │
    ▼ per enabled league
    ├─ claim_league(league_id, section) in DB  ← prevents worker collisions
    │    └─ if another worker holds it → skip
    ├─ checks active session → auto re-login if expired
    ├─ navigates to league URL + dismiss_cookies()
    │
    ├─ PHASE 1 — Round building (if no JSON checkpoint exists):
    │    ├─ extract_info_results() → scrapes match list
    │    │    ├─ detects rounds via HTML: 'event__round--static' or 'event__header'
    │    │    ├─ detects matches via HTML: 'Click for match detail!'
    │    │    └─ saves check_points/{section}/{league}/Round_N.json
    │    └─ [RETRY] up to LEAGUE_NAV_RETRIES=3 on failure
    │
    ├─ PHASE 2 — Match detail extraction:
    │    ├─ loads pending Round_N.json
    │    ├─ per match:
    │    │    ├─ retry_match() up to MATCH_MAX_ATTEMPTS=3
    │    │    ├─ navigates to match URL (#/match-summary)
    │    │    ├─ extracts: teams, score, date, stadium, details
    │    │    │    Special sports: tennis, golf, boxing, F1
    │    │    ├─ save_math_info() + save_score_info() to DB
    │    │    └─ update_league_checkpoint(round, match) in DB
    │    └─ on round complete: deletes Round_N.json
    │
    └─ release_league(league_id, section, 'completed')
         └─ on crash → cleanup_stale_leagues() marks 'interrupted' → auto retry
```

<!-- RISKS (milestone4):
  - Classic CSS selectors (event__score--home/away, event__participant--home/away) are
    fragile — same migration risk as milestone3.
  - Match detection relies on the literal string 'Click for match detail!' in raw HTML.
    If FlashScore changes that text, Phase 1 extracts zero matches silently.
  - time_difference_naive (UTC↔local offset) is computed at module import time (~line 54).
    For long-running processes (days), the offset can become stale.
-->

---

### milestone4 — Special sports

Special sports are handled by `extraction_special_sports()`, called from the same scheduling loop as team sports but with dedicated extraction functions:

| Sport | Function | Status |
|---|---|---|
| Tennis | `get_complete_match_info_tennis()` | ✅ Active — 63 matches in DB |
| Boxing | `extract_info_boxing()` | ✅ Active — 2 matches in DB |
| Formula 1 | `create_events_f1()` | ✅ Active — 2 races, 22 drivers in DB |
| Golf | `get_complete_match_info_golf()` | ✅ Implemented — no active tournament |

After each extraction run, `update_league_stats_json()` automatically updates the `matches` and `teams` counters in `leagues_info.json`.

<!-- RISKS (disabled sports):
  - Re-enabling these sports requires wiring their dedicated functions into the main loop
    and adding them to SUPPORTED_SPORTS — not just setting extract=true in leagues_info.json.
  - Tennis uses get_player_data_tennis() from milestone6 for participant extraction inside
    milestone4 — both files must be in sync when re-enabling tennis.
-->

---

### milestone6 — Players extraction

```
global_check_point.json  +  leagues_season/{sport}/{league}.json
    │
    ▼ per sport in list_sports
    ├─ [RESUME] reads global_check_point[sport][M6]: league_point, team_point, player
    │
    ├─ per league: checks leagues_season/{sport}/{league}.json exists (built by milestone3)
    │
    ├─ per team:
    │    ├─ [RESUME] skips until team_point checkpoint
    │    ├─ navigates to team URL
    │    ├─ finds Squad button → squad_url
    │    ├─ get_squad_list() → player links via lineup lineup--{sport} selector
    │    │    (football maps to 'soccer' in selector)
    │    │
    │    └─ per player link:
    │         ├─ [RESUME] skips until player checkpoint
    │         ├─ get_player_data() → name, country, DOB, photo, position
    │         ├─ check_player_duplicates() → skip if already in DB
    │         ├─ save_player_info() if new
    │         ├─ check_team_player_entity() → save link if not already linked
    │         └─ invalid links logged to check_points/issues/issues_player.json
    │
    └─ on sport complete: removes M6 key from global_check_point[sport]
```

<!-- RISKS (milestone6):
  - Squad button selector (.tabs__tab.squad) is a compound CSS class — fragile if FlashScore changes.
  - get_squad_list() has a typo in default param: sport_id='barketball' (should be 'basketball').
    No runtime impact since the correct value is always passed explicitly.
  - global_check_point.json is a single shared file for all sports and milestones —
    concurrent writes from multiple processes could corrupt it.
-->

---

## Running the Project

```bash
# Activate environment
source /home/you/env/sports_env/bin/activate

# Full system — concurrent live + scheduled scraping
python main.py

# Scheduled scraping only (news, leagues, teams, results, fixtures)
python main1.py

# Live match scraping only
python main2.py

# Manual execution — edit flags inside the file
python main_manual_adjust.py

# Parallel extraction across N sessions
python paralel_execution.py <n_sessions> <section>
# Example: python paralel_execution.py 3 results
```

---

## Configuration

All schedules and toggles live in `check_points/CONFIG.json`:

| Key | Description |
|-----|-------------|
| `DATA_BASE` | Enable/disable PostgreSQL writes |
| `EXTRACT_NEWS.TIME` | Cron-style schedule for news extraction |
| `CREATE_LEAGUES.TIME` | Schedule for league creation |
| `CREATE_TEAMS.TIME` | Schedule for team creation |
| `GET_RESULTS.TIME` | Schedule for results extraction |
| `GET_FIXTURES.TIME` | Schedule for fixtures extraction |
| `GET_PLAYERS.TIME` | Schedule for player data |

Per-league extraction is controlled via `check_points/leagues_info.json` using `extract_results.extract` and `extract_fixtures.extract` flags.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Scraping | Selenium + Firefox/geckodriver (headless) |
| Database | PostgreSQL via psycopg2 |
| Concurrency | ThreadPoolExecutor |
| Terminal UI | Rich (parallel dashboard) |
| IDs | UUID4 + SHA-256 for reproducible IDs |

---

## State Persistence

Two parallel mechanisms keep track of progress:

1. **Checkpoint files** (`check_points/`) — JSON files tracking last processed index, league status, round number. Allows resuming after interruption.
2. **PostgreSQL** — Final storage at remote DB. `DATA_BASE` flag controls whether writes are active.

---

## Selenium Setup

- Firefox with geckodriver, headless mode
- 50% page zoom after load: `document.body.style.zoom='50%'`
- `WebDriverWait` with explicit waits (10–20s timeouts)
- Cookie banner auto-dismissed on every page navigation

---

## Interactive Debugging

Use the Jupyter notebook for step-by-step execution:

```bash
jupyter notebook notebooks/main_depuracion.ipynb
```

To reconnect Claude Code to an active browser session:

```python
from scripts.connect_driver import get_active_driver
driver = get_active_driver()
```

---

## Database

- Host: `96.30.195.40` — database: `sports_db`
- Check current state: `python scripts/db_status.py`
- Sports covered: Football, Basketball, Baseball, Hockey, American Football, Tennis, Golf, Boxing
