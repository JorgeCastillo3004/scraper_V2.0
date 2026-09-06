#!/usr/bin/env python3
"""_debug_tennis_robust.py — ROBUSTEZ: corre el flujo de creación de tenis en SECO
sobre MUCHOS partidos/jugadores de varias ligas y cuenta fallos. NO escribe (saves
bloqueados + save_image stub + BD readonly). Objetivo: confirmar que nunca crashea.

Uso: _debug_tennis_robust.py [target_matches] [section]
  target_matches: total de partidos a procesar (default 25)
  section: 'results' | 'fixtures' | 'both'  (default both)
"""
import os, sys, json, datetime, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT,'scripts')); sys.path.insert(0, os.path.join(ROOT,'src'))

TARGET = int(sys.argv[1]) if len(sys.argv)>1 else 25
SECT   = sys.argv[2] if len(sys.argv)>2 else 'both'
LFILTER= sys.argv[3].lower() if len(sys.argv)>3 else ''   # substring de liga (ej. 'wimbledon')

# campos NOT NULL + maxlen (esquema real)
SCHEMA = {
 'match': {'match_id':(1,128,str),'country_id':(0,17,str),'name':(0,128,str),
   'place':(0,128,str),'league_id':(0,128,str),'stadium_id':(0,128,str),
   'tournament_id':(0,128,str),'rounds':(0,40,str),'season_id':(0,128,str),
   'statistic':(0,4000,str),'status':(0,17,str)},
 'team': {'team_id':(1,128,str),'country_id':(0,17,str),'team_desc':(0,255,str),
   'team_logo':(0,70,str),'team_name':(0,128,str),'sport_id':(1,128,str)},
 'player': {'player_id':(1,128,str),'country_id':(0,17,str),'player_name':(0,255,str),
   'player_photo':(0,128,str),'player_position':(0,128,str)},
}
def vcheck(table,d):
    probs=[]
    for col,(nn,maxlen,pyt) in SCHEMA[table].items():
        if col not in d: probs.append(f'{table}.{col} FALTA'); continue
        v=d[col]
        if v is None and nn: probs.append(f'{table}.{col} NULL')
        elif pyt is str and isinstance(v,str) and maxlen and len(v)>maxlen:
            probs.append(f'{table}.{col} LARGO {len(v)}>{maxlen}')
    return probs

import data_base as DB
import milestone6 as M6
M6.save_image = lambda *a, **k: None
def _block(*a,**k): raise RuntimeError('ESCRITURA BLOQUEADA')
for fn in ['save_team_info','save_player_info','save_league_team_entity','save_team_players_entity',
           'save_math_info','save_details_math_info','save_score_info','save_stadium_in_db','insert_country']:
    if hasattr(DB,fn): setattr(DB,fn,_block)
try:
    DB.ensure_connection()
    try: DB.con.rollback()
    except Exception: pass
    DB.con.set_session(readonly=True)
except Exception: pass

from driver_session import get_driver
import milestone4 as M4
from selenium.webdriver.common.by import By

SPORT_ID = DB.get_dict_sport_id().get('Tennis')
LINFO = json.load(open(os.path.join(ROOT,'check_points','leagues_info.json')))
drv = get_driver(os.path.join(ROOT,'tmp','test_tennis_driver.json'))

def assemble_player(link, league_info):
    M4.wait_update_page(drv, link, 'container__heading')
    pd = M6.get_player_data_tennis(drv)        # REAL (fixed)
    pd['team_id']=pd['player_id']; pd['season_id']=league_info['season_id']
    pd['team_name']=pd['player_name']; pd['team_desc']=''; pd['team_logo']=pd['player_photo']
    pd['sport_id']=league_info['sport_id']
    try: pd['country_id']=DB.get_country_id(pd['player_country'])
    except Exception: pd['country_id']=None
    return pd

stats={'matches':0,'players':0,'singles':0,'doubles':0,'no_photo':0,'no_dob':0,
       'new_country':0,'scheduled':0,'completed':0,'fails':[]}

def process_match(ev, league_info, section):
    try:
        M4.wait_load_details(drv, ev['link_details'])
        ev = M4.get_match_info(drv, ev)
        try: ev['statistic']=M4.get_statistics_game(drv)
        except Exception: ev['statistic']=''
        ev['league_id']=league_info['league_id']; ev['country_id']=league_info['country_id']
        ev['season_id']=league_info['season_id']; ev['tournament_id']=''; ev['rounds']=section
        ev['stadium_id']=M4.generate_uuid(); ev['place']=ev.get('place','')
        if section=='results' and '-' not in str(ev.get('home_result','')) and ev.get('home_result','')!='':
            ev['status']='COMPLETED'; stats['completed']+=1
        else:
            ev['status']='SCHEDULED'; ev['home_result']=-1; ev['visitor_result']=-1; stats['scheduled']+=1
        home,away = M4.get_links_participants(drv)
        stats['matches']+=1
        if len(home)==1: stats['singles']+=1
        else: stats['doubles']+=1
        # validar match
        for p in vcheck('match', ev): stats['fails'].append(f"[{ev.get('name','?')}] {p}")
        # validar cada jugador (la parte que crasheaba)
        for link in (home+away):
            pd = assemble_player(link, league_info)
            stats['players']+=1
            if not pd.get('player_photo'): stats['no_photo']+=1
            if pd.get('player_dob')==datetime.datetime(1900,1,1): stats['no_dob']+=1
            if pd.get('country_id') is None: stats['new_country']+=1
            for p in vcheck('player', pd): stats['fails'].append(f"[{pd.get('player_name','?')}] {p}")
            for p in vcheck('team', pd): stats['fails'].append(f"[{pd.get('player_name','?')}] {p}")
    except Exception as e:
        stats['fails'].append(f"[{ev.get('name','?')}] EXCEPCIÓN {type(e).__name__}: {str(e)[:80]}")

# ligas a recorrer: las que tengan results/fixtures
leagues=[(k,v) for k,v in LINFO.get('TENNIS',{}).items()
         if (v.get('results') or v.get('fixtures')) and (not LFILTER or LFILTER in k.lower())]
sections = ['results','fixtures'] if SECT=='both' else [SECT]
for lkey,raw in leagues:
    if stats['matches']>=TARGET: break
    league_info={'sport_name':'TENNIS','sport_id':SPORT_ID,'league_id':raw['league_id'],
      'league_name':raw['league_name'],'season_id':raw.get('season_id',''),'country_id':raw.get('country_id','')}
    for section in sections:
        if stats['matches']>=TARGET: break
        url = raw.get(section)
        if not url: continue
        try:
            drv.get(url); time.sleep(3)
            rows = drv.find_elements(By.CLASS_NAME,'event__match')
        except Exception as e:
            print(f"  [skip liga {lkey}/{section}: {str(e)[:50]}]"); continue
        # PRE-COLECTAR event_info de TODAS las filas ANTES de navegar (evita stale)
        evs=[]
        for row in rows:
            try: evs.append(M4.get_result(row, league_info['country_id'], section=section))
            except Exception: pass
        print(f"[{lkey} / {section}] filas={len(rows)} parseadas={len(evs)} (procesados={stats['matches']}/{TARGET})", flush=True)
        for ev in evs:
            if stats['matches']>=TARGET: break
            process_match(ev, league_info, section)

print("\n================= RESUMEN ROBUSTEZ =================")
for k in ['matches','players','singles','doubles','completed','scheduled','no_photo','no_dob','new_country']:
    print(f"  {k:12s}: {stats[k]}")
print(f"  FALLOS      : {len(stats['fails'])}")
for f in stats['fails'][:40]: print("    •", f)
print("\nVEREDICTO:", "✅ 0 fallos" if not stats['fails'] else f"❌ {len(stats['fails'])} fallos")
