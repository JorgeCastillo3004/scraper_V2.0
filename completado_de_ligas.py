"""
completado_de_ligas.py — Completar SOLO las ligas pineadas faltantes en DB
==========================================================================
Se conecta al DRIVER VIVO existente (get_driver, sin login ni quit) y, por cada
deporte, reproduce el flujo de milestone2.create_leagues (Opción A acordada):

  1. lee las ligas pineadas de la cuenta (#my-leagues-list)
  2. ENTRA a cada liga pineada (la info completa solo aparece al abrir el link)
  3. verifica en la BASE DE DATOS si la liga ya existe
       - existe  -> continúa con la siguiente (no hace nada)
       - falta   -> la crea (país si falta + liga + season + sections + json)

La verificación de existencia usa la DB (get_dict_results), NO el json
(leagues_info.json a veces está desactualizado) — tal como pidió Jorge.

Deportes por defecto (se pueden acotar con --sports):
  FOOTBALL, BASKETBALL, BASEBALL, AM._FOOTBALL, HOCKEY, TENNIS, GOLF, BOXING,
  FORMULA 1  (caso especial: solo se asegura que la LIGA exista, sin pilotos)

REGLAS: no toca el driver (no quit/close), no borra nada, solo INSERT/UPDATE.

Uso:
  env_sports/bin/python completado_de_ligas.py
  env_sports/bin/python completado_de_ligas.py --sports FOOTBALL BOXING
  env_sports/bin/python completado_de_ligas.py --sports "FORMULA 1"
"""
import os, sys, argparse, traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from driver_session import get_driver
from common_functions import load_json, wait_update_page
import milestone2 as m2
from data_base import get_dict_sport_id, save_sport_database

DEFAULT_SPORTS = ['FOOTBALL', 'BASKETBALL', 'BASEBALL', 'AM._FOOTBALL',
                  'HOCKEY', 'TENNIS', 'GOLF', 'BOXING', 'FORMULA 1']

# alias del caso especial MOTOR SPORT / Fórmula 1
MOTOR_ALIASES = {'FORMULA 1', 'FORMULA_1', 'F1', 'MOTOR SPORT',
                 'MOTORSPORT', 'MOTOR_SPORT'}
MOTOR_SPORT_KEY = 'MOTOR SPORT'   # clave real en sports_url_m2.json / sport.name


def norm_sport(s):
    """'AM. FOOTBALL' -> 'AM._FOOTBALL'; 'football' -> 'FOOTBALL'."""
    return s.strip().upper().replace(' ', '_')


def ensure_formula1(drv):
    """Asegura que la liga FORMULA 1 exista en DB (sin crear pilotos/escuderías).
    Reusa milestone2.find_categories_motor_sport + create_league (idempotente:
    create_league solo guarda si check_league_duplicate da vacío)."""
    print('\n' + '=' * 70)
    print('FORMULA 1 (MOTOR SPORT) — asegurando que la liga exista')
    dict_sports_url = load_json('check_points/sports_url_m2.json')
    url = dict_sports_url.get(MOTOR_SPORT_KEY) or dict_sports_url.get('MOTORSPORT')
    if not url:
        print('  [SKIP] no hay URL de MOTOR SPORT en sports_url_m2.json')
        return

    # sport_id de MOTOR SPORT (crear el deporte si no existe, como milestone2)
    dsid = get_dict_sport_id()
    sport_id = dsid.get(MOTOR_SPORT_KEY)
    if not sport_id:
        cfg = load_json('check_points/CONFIG_M2.json')
        mode = (cfg.get(MOTOR_SPORT_KEY) or {}).get('mode', 'INDIVIDUAL')
        sport_dict, sport_id = m2.create_sport_dict(mode, MOTOR_SPORT_KEY)
        save_sport_database(sport_dict)
        print(f'  deporte MOTOR SPORT creado (sport_id={sport_id})')

    wait_update_page(drv, url, 'container__heading')
    dict_categories = m2.find_categories_motor_sport(drv, ['FORMULA 1'])
    for category, info in dict_categories.items():
        info['league_name'] = category
        dict_league = m2.create_league(drv, info, sport_id)   # guarda solo si falta
        print(f'  liga asegurada: {category} (league_id={dict_league["league_id"]})')


def main():
    ap = argparse.ArgumentParser(description='Completa ligas pineadas faltantes en DB')
    ap.add_argument('--sports', nargs='+', default=None,
                    help='deportes a completar (default: lista estándar)')
    args = ap.parse_args()

    raw = args.sports if args.sports else DEFAULT_SPORTS

    normal_sports, do_motor = [], False
    for s in raw:
        if s.strip().upper() in MOTOR_ALIASES:
            do_motor = True
        else:
            normal_sports.append(norm_sport(s))

    drv = get_driver()
    print(f'driver vivo: {drv.current_url}')
    drv.execute_script("document.body.style.zoom='50%'")   # igual que milestone2

    dict_sports_url = load_json('check_points/sports_url_m2.json')

    print('\n' + '#' * 70)
    print(f'COMPLETADO DE LIGAS  |  {datetime.now():%Y-%m-%d %H:%M:%S}')
    print(f'deportes normales: {normal_sports}  |  FORMULA 1: {do_motor}')
    print('#' * 70)

    resumen = []
    for sport in normal_sports:
        if sport not in dict_sports_url:
            print(f'\n[SKIP] "{sport}" no está en sports_url_m2.json '
                  f'(claves válidas, ej.: AM._FOOTBALL)')
            resumen.append((sport, 'SKIP (sin URL)'))
            continue
        print('\n' + '=' * 70)
        print(f'>>> DEPORTE: {sport}')
        try:
            # Reuso EXACTO del flujo milestone2 (crea solo las faltantes,
            # verificando existencia contra la DB).
            m2.create_leagues(drv, [sport])
            resumen.append((sport, 'OK'))
        except Exception as e:
            print(f'[ERROR] {sport}: {type(e).__name__}: {e}')
            traceback.print_exc()
            resumen.append((sport, f'ERROR: {type(e).__name__}'))

    if do_motor:
        try:
            ensure_formula1(drv)
            resumen.append(('FORMULA 1', 'OK'))
        except Exception as e:
            print(f'[ERROR] FORMULA 1: {type(e).__name__}: {e}')
            traceback.print_exc()
            resumen.append(('FORMULA 1', f'ERROR: {type(e).__name__}'))

    print('\n' + '#' * 70)
    print('RESUMEN POR DEPORTE')
    for sport, estado in resumen:
        print(f'  {sport:<16} -> {estado}')
    print('#' * 70)
    print('[done] driver vivo intacto (no se hizo quit/close).')


if __name__ == '__main__':
    main()
