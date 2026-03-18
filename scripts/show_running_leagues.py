"""
show_running_leagues.py

Muestra la tabla running_leagues completa en formato visual.

Uso:
  source /home/you/env/sports_env/bin/activate
  python scripts/show_running_leagues.py
"""

import sys
import os
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.text import Text

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from data_base import getdb

STATUS_STYLE = {
    'running':     'bold green',
    'completed':   'cyan',
    'interrupted': 'yellow',
}

def main():
    console = Console()
    con = getdb()
    cur = con.cursor()

    cur.execute("""
        SELECT rl.league_id, COALESCE(l.league_name, rl.league_id) AS league_name,
               rl.section, rl.host, rl.started_at, rl.status,
               rl.current_round, rl.current_match
        FROM running_leagues rl
        LEFT JOIN league l ON l.league_id = rl.league_id
        ORDER BY
            CASE rl.status WHEN 'running' THEN 0 WHEN 'interrupted' THEN 1 ELSE 2 END,
            rl.started_at DESC
    """)
    rows = cur.fetchall()
    con.close()

    table = Table(
        title=f'running_leagues  —  {len(rows)} registro(s)  —  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        show_header=True,
        show_lines=True,
    )
    table.add_column('league_name',   no_wrap=True)
    table.add_column('section',       justify='center')
    table.add_column('host',          style='dim')
    table.add_column('started_at',    justify='center')
    table.add_column('status',        justify='center')
    table.add_column('current_round', justify='center')
    table.add_column('current_match')

    for league_id, league_name, section, host, started_at, status, cur_round, cur_match in rows:
        style = STATUS_STYLE.get(status, 'white')
        elapsed = ''
        if started_at:
            delta = datetime.utcnow() - started_at
            h, rem = divmod(int(delta.total_seconds()), 3600)
            m = rem // 60
            elapsed = f'\n[dim]{h}h {m:02d}m ago[/dim]'

        table.add_row(
            str(league_name),
            f'[bold]{section}[/bold]',
            host or '—',
            (started_at.strftime('%Y-%m-%d\n%H:%M:%S') + elapsed) if started_at else '—',
            f'[{style}]{status}[/{style}]',
            cur_round or '[dim]—[/dim]',
            cur_match or '[dim]—[/dim]',
        )

    console.print()
    console.print(table)
    console.print()

if __name__ == '__main__':
    main()
