#!/usr/bin/env python3
"""_debug_tennis_write_one.py — Crea UN SOLO partido de tenis (camino real corregido).

ESCRIBE en la BD (autorizado por el usuario para 1 partido). Límite duro = 1 match.
Usa las funciones REALES: save_team_player_single + save_math_info + save_details +
save_score (mismas que get_complete_match_info_tennis, para 1 match). Captura todos
los IDs generados y los imprime para la verificación read-only posterior.
NO borra nada. Dedup previo con check_match_duplicate para no duplicar.
"""
import os, sys, json
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT,'scripts')); sys.path.insert(0, os.path.join(ROOT,'src'))

from driver_session import get_driver
import milestone4 as M4
import data_base as DB
from selenium.webdriver.common.by import By
import time

LINFO = json.load(open(os.path.join(ROOT,'check_points','leagues_info.json')))
def find_league(sub):
    for k,v in LINFO.get('TENNIS',{}).items():
        if sub.lower() in k.lower(): return k,v
    return None,None
key, raw = find_league('WTA Wimbledon')
# sport_id = UUID real de la tabla sport (NO 'TENNIS'). sport_name='TENNIS' (project)
# se usa para el branch en save_team_player_single y rutas; sport_id (UUID) para la FK.
SPORT_ID_TENNIS = DB.get_dict_sport_id().get('Tennis')
assert SPORT_ID_TENNIS, "No pude resolver sport_id de 'Tennis' en la tabla sport"
league_info = {'sport_name':'TENNIS','sport_id':SPORT_ID_TENNIS,
  'league_id':raw['league_id'],'league_name':raw['league_name'],
  'season_id':raw.get('season_id',''),'country_id':raw.get('country_id','')}
print('Liga:', key, '| league_id:', league_info['league_id'], '| sport_id:', SPORT_ID_TENNIS)

drv = get_driver(os.path.join(ROOT,'tmp','test_tennis_driver.json'))
url = raw.get('results') or raw['url']
print('Navegando results:', url)
drv.get(url); time.sleep(4)
rows = drv.find_elements(By.CLASS_NAME,'event__match')
print('Filas:', len(rows))

# ── elegir 1 partido COMPLETADO singles que NO exista en BD ────────────────────
chosen = None
for row in rows:
    try:
        ev = M4.get_result(row, league_info['country_id'], section='results')
    except Exception:
        continue
    if '-' in str(ev.get('home_result','')) or ev.get('home_result','')=='':
        continue  # saltar sin score (no completado)
    chosen = ev; break
if not chosen:
    print('[STOP] No hallé un partido completado utilizable'); sys.exit(0)

event_info = chosen
print('\nCandidato:', event_info['name'], '| score', event_info['home_result'],'-',event_info['visitor_result'])

# completar desde el detalle (igual que get_complete_match_info_tennis)
url_details = event_info['link_details']
M4.wait_load_details(drv, url_details)
event_info = M4.get_match_info(drv, event_info)
try: event_info['statistic'] = M4.get_statistics_game(drv)
except Exception as e: event_info['statistic']=''; print('  (stats falló:', str(e)[:50],')')
event_info['league_id']=league_info['league_id']; event_info['country_id']=league_info['country_id']
raw_date = drv.find_element(By.CLASS_NAME,'duelParticipant__startTime').text
event_info['match_date'], event_info['start_time'] = M4.get_time_date_format(raw_date, section='results')
event_info['end_time']=event_info['start_time']
event_info['status']='COMPLETED'
event_info['season_id']=league_info['season_id']; event_info['tournament_id']=''
event_info['rounds']='results'

# DEDUP: ¿ya existe?
dup = DB.check_match_duplicate(event_info['league_id'], event_info['match_date'], event_info['name'])
if dup:
    print(f'[STOP] Ese partido YA existe en BD (match_id={dup}). No escribo.'); sys.exit(0)
print('Dedup OK (no existe). match_id a crear:', event_info['match_id'])

# ── participantes (REAL, con escritura: player/team/league_team/team_players) ──
home_links, away_links = M4.get_links_participants(drv)
print('home:', home_links, '| away:', away_links)
assert len(home_links)==1 and len(away_links)==1, 'Este test de escritura es SOLO singles'

print('\n>>> ESCRIBIENDO participantes...')
team_id_home = M4.save_team_player_single(drv, home_links[0], league_info)
team_id_away = M4.save_team_player_single(drv, away_links[0], league_info)
print('team_id_home:', team_id_home, '| team_id_away:', team_id_away)

# stadium (camino real)
event_info['stadium_id'] = M4.generate_uuid()
name_stadium = event_info.get('VENUE','')
st = DB.get_stadium_id(name_stadium)
if st:
    event_info['stadium_id'] = st[0]; print('stadium reutilizado:', st[0])
else:
    dict_stadium = {'stadium_id':event_info['stadium_id'],'country':event_info.get('match_country',''),
                    'capacity':0,'desc_i18n':'','name':name_stadium,'photo':''}
    DB.save_stadium_in_db(dict_stadium); print('stadium creado:', event_info['stadium_id'])

# match + detail + score (REAL)
def _pts(v):
    try: return float(v)
    except (TypeError,ValueError): return -1.0
mdid_h=M4.generate_uuid(); sc_h=M4.generate_uuid()
mdid_v=M4.generate_uuid(); sc_v=M4.generate_uuid()
dict_home={'match_detail_id':mdid_h,'home':True,'visitor':False,'match_id':event_info['match_id'],
           'team_id':team_id_home,'points':_pts(event_info['home_result']),'score_id':sc_h}
dict_visitor={'match_detail_id':mdid_v,'home':False,'visitor':True,'match_id':event_info['match_id'],
              'team_id':team_id_away,'points':_pts(event_info['visitor_result']),'score_id':sc_v}

print('>>> ESCRIBIENDO match/detail/score...')
DB.save_math_info(event_info)
DB.save_details_math_info(dict_home)
DB.save_details_math_info(dict_visitor)
DB.save_score_info(dict_home)
DB.save_score_info(dict_visitor)

print('\n===== CREADO OK — IDs para verificar =====')
print(json.dumps({
  'match_id':event_info['match_id'],'name':event_info['name'],
  'league_id':event_info['league_id'],'season_id':event_info['season_id'],
  'country_id':event_info['country_id'],'stadium_id':event_info['stadium_id'],
  'match_detail_home':mdid_h,'match_detail_visitor':mdid_v,
  'score_home':sc_h,'score_visitor':sc_v,
  'team_id_home':team_id_home,'team_id_away':team_id_away,
}, indent=2))
# guardar para el verificador
open(os.path.join(ROOT,'tmp','_last_written_match.json'),'w').write(json.dumps({'match_id':event_info['match_id']}))
print('\n[FIN] 1 partido escrito.')
