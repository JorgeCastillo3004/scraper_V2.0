"""
_debug_results_coverage.py — diagnóstico de los [FALTA] de update_pending.

Por cada liga seleccionada:
  1) ¿el results_url existe / carga? (heading + "No match found")
  2) ¿tiene partidos? hasta qué fecha llega (más nueva / más antigua) tras Show-more
  3) clasifica CADA partido FALTA en una causa:
       - FUERA_DE_RANGO : su fecha es más vieja que la más antigua que muestra /results
       - NOMBRE         : su fecha SÍ está en el rango pero los nombres de equipo
                          (normalizados) NO aparecen juntos en ninguna fila → desajuste de nombre
       - MATCHER        : fecha en rango y AMBOS nombres aparecen en una fila → el matcher
                          estricto falló igual (revisar has_tip / get_result)
Reusa el driver VIVO (get_driver) y las funciones de fix_live_matches. No hace quit().
"""
import os, sys, re
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
for p in (ROOT, os.path.join(ROOT, 'scripts'), os.path.join(ROOT, 'src')):
    sys.path.insert(0, p)

from selenium.webdriver.common.by import By
from driver_session import get_driver
from fix_live_matches import (load_until_date, scan_results_page, _norm_team,
                              _no_match_visible, get_result, parse_flashscore_date,
                              wait_update_page, dismiss_cookies)
import json

LEAGUES_INFO = json.load(open(os.path.join(ROOT, 'check_points', 'leagues_info.json')))

# (sport, league_key) a diagnosticar — muestra representativa
TARGETS = [
    ('AM._FOOTBALL', 'USA_NFL'),
    ('FOOTBALL', 'BOLIVIA_Division Profesional'),
    ('FOOTBALL', 'ECUADOR_Liga Pro'),
    ('FOOTBALL', 'EUROPE_Conference League'),
    ('FOOTBALL', 'BRAZIL_Serie A Betano'),
]

def parse_falta_from_log(path):
    """Devuelve {results_url: [(date_str, 'home~visitor'), ...]} desde el log."""
    out, cur = {}, None
    for line in open(path, encoding='utf-8', errors='ignore'):
        m = re.search(r'results_url:\s*(\S+)', line)
        if m:
            cur = m.group(1).rstrip('/'); out.setdefault(cur, [])
            continue
        f = re.search(r'\[FALTA\]\s*([0-9-]+)\s*\|\s*(.+)', line)
        if f and cur is not None:
            out[cur].append((f.group(1).strip(), f.group(2).strip()))
    return out

def all_rows_text(driver):
    rows = driver.find_elements(By.XPATH, '//div[contains(@class,"leagues--static event--leagues")]/div')
    blob = []
    for r in rows:
        try:
            blob.append(_norm_team(r.get_attribute('textContent') or ''))
        except Exception:
            pass
    return rows, ' || '.join(blob)

def main():
    drv = get_driver()
    print('driver en:', drv.current_url)
    falta_by_url = parse_falta_from_log(os.path.join(ROOT, 'logs', '_update_pending_apply.out'))

    for sport, key in TARGETS:
        info = LEAGUES_INFO.get(sport, {}).get(key, {})
        url = (info.get('results') or '').rstrip('/')
        print('\n' + '=' * 78)
        print(f'### {sport} / {key}')
        print('results_url:', url or '(NO HAY results en leagues_info)')
        if not url:
            continue
        # 1) ¿carga?
        try:
            wait_update_page(drv, url + '/', 'container__heading')
            dismiss_cookies(drv)
        except Exception as e:
            print('  [LINK] NO CARGA / error:', e); continue
        if _no_match_visible(drv):
            print('  [LINK] carga pero "No match found" — SIN PARTIDOS'); continue
        print('  [LINK] OK, carga y tiene partidos')

        # 2) cargar todo (Show more hasta que desaparezca) y ver rango de fechas
        load_until_date(drv, date(2000, 1, 1))   # target inalcanzable → carga todo lo disponible
        rows, blob = all_rows_text(drv)
        dates = []
        for r in rows:
            try:
                if 'Click for' not in (r.get_attribute('outerHTML') or ''):
                    continue
                d = parse_flashscore_date(get_result(r, country_id='', section='results')['match_date'])
                if d: dates.append(d)
            except Exception:
                pass
        if not dates:
            print('  [RANGO] no pude parsear fechas'); continue
        newest, oldest = max(dates), min(dates)
        print(f'  [RANGO] partidos en página: {len(dates)} | más NUEVO={newest} | más ANTIGUO={oldest}')

        # 3) clasificar los FALTA de esta liga
        faltas = falta_by_url.get(url, [])
        causa = {'FUERA_DE_RANGO': 0, 'NOMBRE': 0, 'MATCHER': 0}
        ejemplos = {'FUERA_DE_RANGO': [], 'NOMBRE': [], 'MATCHER': []}
        for ds, name in faltas:
            try:
                fd = date.fromisoformat(ds)
            except Exception:
                fd = None
            home, _, vis = name.partition('~')
            hn, vn = _norm_team(home), _norm_team(vis)
            both_present = (hn in blob) and (vn in blob)
            if fd and fd < oldest:
                c = 'FUERA_DE_RANGO'
            elif both_present:
                c = 'MATCHER'
            else:
                c = 'NOMBRE'
            causa[c] += 1
            if len(ejemplos[c]) < 4:
                ej = f'{ds} {name}'
                if c == 'NOMBRE':
                    ej += f'  [home_en_pag={hn in blob} away_en_pag={vn in blob}]'
                ejemplos[c].append(ej)
        print(f'  [FALTA={len(faltas)}] -> {causa}')
        for c, lst in ejemplos.items():
            for e in lst:
                print(f'      ({c}) {e}')

if __name__ == '__main__':
    main()
