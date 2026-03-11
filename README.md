# Sports Data Scraper

Multi-sport data aggregation system that scrapes **FlashScore.com** using Selenium and stores data in PostgreSQL. Covers Football, Basketball, Baseball, Hockey, American Football, Tennis, Golf, and Boxing — collecting leagues, teams, matches, fixtures, news, and player data.

---

## Architecture

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
│   └── get_last_changes.py  # Show recent DB changes
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
