"""
_debug_scan_results.py — debug puntual de scan_results_page

Se conecta al driver vivo del notebook (sin abrir browser nuevo) usando
`driver_session.get_driver()`. Asume que el driver ya esta en la pagina
results/ de la liga reportada (Euroleague).

Diagnostica los [NOT FOUND] devolviendo, por par:
 - hits estrictos (matcher actual: home.lower() in row.text.lower() AND ...)
 - hits laxos (ignorando guiones y espacios: 'Hapoel Tel-Aviv' = 'Hapoel Tel Aviv')
 - fecha del match en DB
 - rango de fechas que tiene la pagina cargada en ESTE momento
 - como aparece el nombre real de cada equipo en la pagina
"""

import os
import re
import sys
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from selenium.webdriver.common.by import By
import psycopg2

from driver_session import get_driver
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS


# Matches reportados como [NOT FOUND] en la ultima corrida del notebook (Euroleague)
NOT_FOUND_PAIRS = [
    ('Hapoel Tel-Aviv',  'Zalgiris Kaunas'),
    ('Hapoel Tel-Aviv',  'Dubai'),
    ('Hapoel Tel-Aviv',  'Paris'),
    ('Hapoel Tel-Aviv',  'Anadolu Efes'),
    ('Lyon-Villeurbanne','Hapoel Tel-Aviv'),
    ('Barcelona',        'Dubai'),
    ('Valencia',         'Paris'),
    ('Monaco',           'Crvena zvezda'),
    ('Real Madrid',      'Olimpia Milano'),
    ('Panathinaikos',    'Baskonia'),
    ('Lyon-Villeurbanne','Zalgiris Kaunas'),
    ('Bayern',           'Partizan Mozzart Bet'),
    ('Olympiacos',       'Maccabi Tel Aviv'),
    ('Virtus Bologna',   'Fenerbahce'),
]


def normalize(s):
    return s.lower().replace('-', '').replace(' ', '')


def fetch_db_dates(pairs):
    """Devuelve {'home~visitor': (match_date, status, match_id)} de la liga
    Euroleague (basketball) para los pares de interes."""
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()
    names = ['%s~%s' % p for p in pairs]
    cur.execute("""
        SELECT m.name, m.match_date, m.status, m.match_id
        FROM match m
        JOIN league l ON m.league_id = l.league_id
        JOIN sport  s ON l.sport_id  = s.sport_id
        WHERE s.name = 'Basketball'
          AND l.league_name = 'Euroleague'
          AND m.name = ANY(%s)
    """, (names,))
    rows = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    cur.close(); con.close()
    return rows


def parse_visible_dates(rows):
    """Extrae fechas DD.MM. del texto de las filas visibles para conocer rango."""
    dates = []
    pat = re.compile(r'\b(\d{2})\.(\d{2})\.\b')
    for r in rows:
        try:
            for m in pat.finditer(r.text):
                dates.append('%s-%s' % (m.group(2), m.group(1)))  # MM-DD
        except Exception:
            continue
    return sorted(set(dates))


def main():
    drv = get_driver()
    print('URL actual: %s' % drv.current_url)
    print('Titulo    : %s' % drv.title)

    xpath_rows = '//div[contains(@class,"leagues--static event--leagues")]/div'
    rows = drv.find_elements(By.XPATH, xpath_rows)
    print('Filas visibles en results: %d' % len(rows))
    if not rows:
        print('No hay filas — el driver no esta en la pagina results/.')
        return

    # Rango de fechas visibles (formato dd.mm. en FlashScore)
    visible = parse_visible_dates(rows)
    if visible:
        print('Rango de fechas visibles (MM-DD, sin año): %s ... %s' % (visible[0], visible[-1]))
        print('Total fechas distintas en pagina: %d' % len(visible))

    # Fechas reales de cada match en DB
    db_dates = fetch_db_dates(NOT_FOUND_PAIRS)

    # Cómo aparece cada equipo en la pagina
    print('\n=== Como aparece cada equipo en la pagina ===')
    interesting = sorted({t for p in NOT_FOUND_PAIRS for t in p})
    for needle in interesting:
        soft = normalize(needle)
        found_lines = []
        for row in rows:
            try:
                lines = row.text.splitlines()
            except Exception:
                continue
            for ln in lines:
                if soft in normalize(ln):
                    found_lines.append(ln.strip())
        uniq = sorted(set(found_lines))[:4]
        flag = '' if uniq else '  <-- NUNCA APARECE'
        print('  [%s]%s  -> %s' % (needle, flag, uniq))

    # Diagnostico por par
    print('\n=== Diagnostico por par ===')
    for home, visitor in NOT_FOUND_PAIRS:
        hn_s = home.lower()
        vn_s = visitor.lower()
        hn_l = normalize(home)
        vn_l = normalize(visitor)
        strict = 0
        loose  = 0
        sample = None
        for row in rows:
            try:
                t = row.text
            except Exception:
                continue
            tlow  = t.lower()
            tnorm = normalize(t)
            if hn_s in tlow and vn_s in tlow:
                strict += 1
            if hn_l in tnorm and vn_l in tnorm:
                loose += 1
                if sample is None:
                    sample = [ln for ln in t.splitlines() if ln.strip()][:4]

        name = '%s~%s' % (home, visitor)
        md, status, mid = db_dates.get(name, (None, None, None))
        if strict:
            tag = 'OK_STRICT'
        elif loose:
            tag = 'BUG_MATCHER_LAXO_VS_GUION'
        else:
            tag = 'NO_EN_PAGINA (falta cargar mas?)'
        print('  %-40s  db_date=%s status=%s  strict=%d laxo=%d  [%s]' % (
            name, md, status, strict, loose, tag))
        if sample and not strict:
            print('       muestra laxa: %s' % ' | '.join(sample))


if __name__ == '__main__':
    main()
