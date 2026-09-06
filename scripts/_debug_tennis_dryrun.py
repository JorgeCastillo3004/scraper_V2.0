#!/usr/bin/env python3
"""_debug_tennis_dryrun.py — PRUEBA EN SECO de la creación de partidos de tenis.

NO escribe NADA: ni BD, ni disco, ni checkpoints. Replica el armado de dicts del
flujo real (save_team_player_single / get_complete_match_info_tennis) y valida cada
campo contra el esquema real introspectado. Neutraliza save_image / save_*  /
insert_country, y pone la conexión de la BD en readonly como red de seguridad.

Usa el DRIVER DE PRUEBA dedicado (tmp/test_tennis_driver.json), nunca el live ni el
de corrección. Solo navega (driver propio) y hace SELECTs read-only opcionales.
"""
import os, sys, json, datetime
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# ── Esquema real (introspectado read-only) : col -> (not_null, maxlen, pytype) ──
NONE = None
SCHEMA = {
 'match': {'match_id':(1,128,str),'country_id':(0,17,str),'end_time':(0,NONE,'time'),
   'match_date':(0,NONE,'date'),'name':(0,128,str),'place':(0,128,str),
   'start_time':(0,NONE,'time'),'league_id':(0,128,str),'stadium_id':(0,128,str),
   'tournament_id':(0,128,str),'rounds':(0,40,str),'season_id':(0,128,str),
   'statistic':(0,4000,str),'status':(0,17,str)},
 'match_detail': {'match_detail_id':(1,128,str),'home':(0,NONE,bool),'visitor':(0,NONE,bool),
   'match_id':(0,128,str),'team_id':(0,128,str)},
 'score_entity': {'score_id':(1,128,str),'points':(1,NONE,'num'),'match_detail_id':(0,128,str)},
 'team': {'team_id':(1,128,str),'country_id':(0,17,str),'team_desc':(0,255,str),
   'team_logo':(0,70,str),'team_name':(0,128,str),'sport_id':(1,128,str)},
 'player': {'player_id':(1,128,str),'country_id':(0,17,str),'player_dob':(0,NONE,'date'),
   'player_name':(0,255,str),'player_photo':(0,128,str),'player_position':(0,128,str)},
 'league_team': {'instance_id':(1,128,str),'team_meta':(0,1024,str),'team_position':(0,NONE,int),
   'league_id':(1,128,str),'season_id':(1,128,str),'team_id':(1,128,str)},
 'team_players_entity': {'player_meta':(0,1024,str),'season_id':(1,128,str),
   'team_id':(1,128,str),'player_id':(1,128,str)},
}

ISSUES = []
def validate(table, d, label=''):
    print(f"\n--- VALIDA {table} {label} ---")
    cols = SCHEMA[table]
    for col,(nn,maxlen,pyt) in cols.items():
        present = col in d
        val = d.get(col, '<<MISSING>>')
        prob = []
        if not present:
            prob.append('FALTA CAMPO')
        else:
            if val is None and nn:
                prob.append('NULL en NOT NULL')
            if pyt=='num':
                if not isinstance(val,(int,float)): prob.append(f'no numérico ({type(val).__name__})')
            elif pyt=='date':
                if not isinstance(val,(datetime.date,datetime.datetime)): prob.append(f'no date ({type(val).__name__})')
            elif pyt=='time':
                pass
            elif pyt is bool:
                if not isinstance(val,bool): prob.append(f'no bool ({type(val).__name__})')
            elif pyt is int:
                if not isinstance(val,int): prob.append(f'no int ({type(val).__name__})')
            elif pyt is str:
                if not isinstance(val,str): prob.append(f'no str ({type(val).__name__})')
                elif maxlen and len(val)>maxlen: prob.append(f'LARGO {len(val)}>{maxlen}')
        extra = '' if not prob else '   <<< ' + ' | '.join(prob)
        sval = repr(val)[:60]
        if prob: ISSUES.append(f'{table}.{col} {label}: {" | ".join(prob)} (val={sval})')
        print(f"   {'NN' if nn else '  '} {col:20s} = {sval}{extra}")
    # columnas extra en el dict que NO son de la tabla (informativo, no error)

# ── Neutralizar TODO lo que escribe (BD/disco) ─────────────────────────────────
import data_base as DB
import milestone6 as M6
def _block(*a, **k): raise RuntimeError('ESCRITURA BLOQUEADA en dry-run')
for fn in ['save_team_info','save_player_info','save_league_team_entity',
           'save_team_players_entity','save_math_info','save_details_math_info',
           'save_score_info','save_stadium_in_db','insert_country','update_league_checkpoint']:
    if hasattr(DB, fn): setattr(DB, fn, _block)
M6.save_image = lambda *a, **k: None          # no descarga foto a disco
# red de seguridad: conexión read-only a nivel servidor (rollback antes de set_session)
try:
    DB.ensure_connection()
    try: DB.con.rollback()
    except Exception: pass
    DB.con.set_session(readonly=True); print('[guard] DB readonly ON')
except Exception as e:
    print('[guard] no se pudo poner readonly (seguimos, saves ya bloqueados):', e)

from driver_session import get_driver
import milestone4 as M4
from selenium.webdriver.common.by import By

# ── league_info de Wimbledon desde leagues_info.json ───────────────────────────
LINFO = json.load(open(os.path.join(ROOT,'check_points','leagues_info.json')))
def find_league(substr):
    for k,v in LINFO.get('TENNIS',{}).items():
        if substr.lower() in k.lower(): return k,v
    return None,None
key, raw = find_league('WTA Wimbledon')
if not raw: key, raw = find_league('Wimbledon')
print(f"\nLiga de prueba: {key}")
league_info = {
  'sport_name':'TENNIS', 'sport_id': raw.get('sport_id','TENNIS'),
  'league_id': raw['league_id'], 'league_name': raw['league_name'],
  'season_id': raw.get('season_id',''), 'country_id': raw.get('country_id',''),
}
print('league_info:', league_info)

drv = get_driver(os.path.join(ROOT,'tmp','test_tennis_driver.json'))
print('Driver de prueba OK. URL actual:', drv.current_url)

# ── Navegar a results/fixtures y tomar la 1a fila de match ─────────────────────
url = raw.get('results') or raw.get('fixtures') or raw['url']
print('Navegando a:', url)
drv.get(url); import time as _t; _t.sleep(4)
rows = drv.find_elements(By.CLASS_NAME, 'event__match')
print(f"Filas event__match encontradas: {len(rows)}")
if not rows:
    print('[STOP] No hay filas de match en esta URL. Probar fixtures/otra liga.'); sys.exit(0)

# build match dict (event_info) con la función real get_result (nombres CORTOS)
section = 'results' if raw.get('results') else 'fixtures'
event_info = None
for row in rows[:8]:
    try:
        event_info = M4.get_result(row, league_info['country_id'], section=section)
        break
    except Exception as e:
        print('  (fila saltada:', type(e).__name__, str(e)[:60], ')')
if not event_info:
    print('[STOP] get_result no pudo armar ninguna fila'); sys.exit(0)
print('\nMATCH dict base (get_result):', {k:str(v)[:40] for k,v in event_info.items()})

# completar como get_complete_match_info_tennis (sin escribir)
url_details = event_info['link_details']
print('\nNavegando al detalle:', url_details)
M4.wait_load_details(drv, url_details)
event_info = M4.get_match_info(drv, event_info)
try:
    event_info['statistic'] = M4.get_statistics_game(drv)
except Exception as e:
    event_info['statistic'] = ''; print('  (get_statistics_game falló:', str(e)[:60], ')')
event_info['league_id'] = league_info['league_id']
event_info['country_id'] = league_info['country_id']
try:
    raw_date = drv.find_element(By.CLASS_NAME,'duelParticipant__startTime').text
    event_info['match_date'], event_info['start_time'] = M4.get_time_date_format(raw_date, section='results')
    event_info['end_time'] = event_info['start_time']
except Exception as e:
    print('  (fecha detalle falló:', str(e)[:60], ')')
if section=='results' and '-' not in str(event_info.get('home_result','')):
    event_info['status']='COMPLETED'
else:
    event_info['status']='SCHEDULED'; event_info['home_result']=-1; event_info['visitor_result']=-1
event_info['season_id']=league_info['season_id']; event_info['tournament_id']=''
event_info['rounds']=(section or 'results')
event_info['stadium_id']=M4.generate_uuid()

# ── participantes (jugadores) ─────────────────────────────────────────────────
home_links, away_links = M4.get_links_participants(drv)
print(f"\nhome_links={home_links}\naway_links={away_links}")
is_singles = len(home_links)==1
print('Tipo de partido:', 'SINGLES' if is_singles else f'DOUBLES (home={len(home_links)})')

def tolerant_player_data(driver):
    """Replica get_player_data_tennis pero TOLERANTE a la foto faltante, para
    poder validar el resto de campos. Marca si la función REAL habría crasheado."""
    from selenium.webdriver.common.by import By as _By
    info = M6.get_all_player_info_tennis(driver)
    pb = driver.find_element(_By.CLASS_NAME, 'container__heading')
    player_country = pb.find_element(_By.XPATH, './/span[@class="breadcrumb__text"]').text
    if 'Age' in info or 'age' in info:
        k = 'Age' if 'Age' in info else 'age'
        date_str = info[k].split('(')[1].replace(')','').strip()
        player_dob = M6.datetime.strptime(date_str, "%d.%m.%Y")
    else:
        player_dob = M6.datetime.strptime('01.01.1900', "%d.%m.%Y")
    player_name = M6.clean_field(pb.find_element(_By.XPATH, './/div[@class="heading__name"]').text)
    # ── la parte FRÁGIL del código real ──
    real_would_crash = False
    photo_diag = ''
    try:
        img = pb.find_element(_By.XPATH, './/img[@loading="eager"]').get_attribute('src')
        photo_diag = f'img eager OK: {img[:40]}'
        player_photo = M6.random_name_logos(player_name, folder='images/players/').replace('images/players/','')
    except Exception:
        real_would_crash = True
        # diagnóstico: ¿qué imgs hay en el header?
        imgs = pb.find_elements(_By.XPATH, './/img')
        photo_diag = f'SIN img[@loading=eager]; imgs en header={len(imgs)}'
        if imgs:
            photo_diag += f' (1a src={imgs[0].get_attribute("src")[:50]})'
        player_photo = ''   # fallback para seguir validando
    pid = M6.random_id_text(player_country + player_name)
    if real_would_crash:
        ISSUES.append(f"get_player_data_tennis CRASHEARÍA en jugador '{player_name}': {photo_diag} (milestone6:30 sin try/except)")
    print(f"   [foto] {photo_diag}")
    return {'player_id':pid,'player_country':player_country,'player_dob':player_dob,
            'player_name':player_name,'player_photo':player_photo,'player_position':''}

def build_player_dicts(link):
    """Replica save_team_player_single SIN guardar. Devuelve player_dict completo."""
    M4.wait_update_page(drv, link, 'container__heading')
    pd = M6.get_player_data_tennis(drv)               # FUNCIÓN REAL YA CORREGIDA (save_image stub)
    pd['team_id']=pd['player_id']; pd['season_id']=league_info['season_id']
    pd['team_country']=pd['player_country']; pd['team_name']=pd['player_name']
    pd['team_desc']=''; pd['team_logo']=pd['player_photo']; pd['sport_id']=league_info['sport_id']
    pd['instance_id']=M4.generate_uuid(); pd['player_meta']=''; pd['team_meta']=''
    pd['team_position']=0; pd['league_id']=league_info['league_id']
    # country_id: SELECT read-only (sin insert_country, que está bloqueado)
    try:
        cid = DB.get_country_id(pd['player_country'])
    except Exception as e:
        cid=None; print('   (get_country_id falló:',str(e)[:50],')')
    pd['country_id']=cid
    if cid is None:
        ISSUES.append(f"country '{pd['player_country']}' NO existe en DB → el flujo real haría insert_country (escritura)")
    return pd

print("\n================= VALIDACIÓN DE CAMPOS =================")
pd_home = build_player_dicts(home_links[0])
validate('player', pd_home, 'home'); validate('team', pd_home, 'home')
validate('league_team', pd_home, 'home'); validate('team_players_entity', pd_home, 'home')
team_id_home = pd_home['team_id']

pd_away = build_player_dicts(away_links[0])
team_id_away = pd_away['team_id']

# match + detail + score
validate('match', event_info, '(match)')
def _pts(v):
    try: return float(v)
    except (TypeError, ValueError): return -1.0
dh = {'match_detail_id':M4.generate_uuid(),'home':True,'visitor':False,
      'match_id':event_info['match_id'],'team_id':team_id_home,
      'points':_pts(event_info['home_result']),'score_id':M4.generate_uuid()}
dv = {'match_detail_id':M4.generate_uuid(),'home':False,'visitor':True,
      'match_id':event_info['match_id'],'team_id':team_id_away,
      'points':_pts(event_info['visitor_result']),'score_id':M4.generate_uuid()}
validate('match_detail', dh, 'home'); validate('score_entity', dh, 'home')
validate('match_detail', dv, 'visitor'); validate('score_entity', dv, 'visitor')

print("\n================= RESUMEN =================")
if not ISSUES:
    print("OK — todos los campos presentes, con tipo y longitud válidos. 0 problemas.")
else:
    print(f"{len(ISSUES)} PROBLEMA(S) detectado(s):")
    for i in ISSUES: print('  •', i)
print("\n[FIN] dry-run sin escrituras (BD readonly + saves bloqueados + save_image stub)")
