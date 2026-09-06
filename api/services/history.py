"""
History service
---------------
Dos cosas para el panel:

1. Visor de `db_history` (snapshots de la DB): lista de snapshots + el texto de la
   comparación de cada snapshot contra el anterior, REPRODUCIENDO TAL CUAL la salida
   del script `scripts/db_history.py` (se captura el stdout de `show_comparison`).
   Tomar un snapshot nuevo consulta el remoto (solo SELECT — autorizado por el usuario).

2. Estado por liga leído de los logs `logs/update_matches_*.log`: última ejecución
   (del nombre del archivo) + cobertura final ("encontrados X / Y en DB") + estado.
"""

import io
import os
import re
import glob
import importlib.util
from contextlib import redirect_stdout
from datetime import datetime

from api.config import PROJECT_ROOT, LOGS_DIR

# ── Cargar el módulo scripts/db_history.py (reusar su lógica, no reescribirla) ──
_DBH_PATH = os.path.join(PROJECT_ROOT, 'scripts', 'db_history.py')
_spec = importlib.util.spec_from_file_location('db_history', _DBH_PATH)
db_history = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db_history)   # importar NO conecta a la DB (la conexión vive en get_snapshot)


# ── Visor de db_history ───────────────────────────────────────────────────────

def list_snapshots() -> list[dict]:
    """Lista compacta de snapshots para el navegador (más reciente último)."""
    history = db_history.load_history()
    out = []
    for i, h in enumerate(history):
        out.append({
            'idx':            i,
            'timestamp':      h.get('timestamp'),
            'total_matches':  h.get('total_matches'),
            'completed':      h.get('status_counts', {}).get('COMPLETED'),
            'with_stats':     h.get('matches_with_stats'),
            'score_minus_one': h.get('score_minus_one'),
        })
    return out


def _first_snapshot_text(snapshot: dict) -> str:
    """Reproduce el bloque 'Primer snapshot' de db_history.main (cuando no hay anterior)."""
    return (
        '\nPrimer snapshot guardado: %s\n' % snapshot.get('timestamp')
        + '  Total deportes : %s  %s\n' % (snapshot.get('total_sports', '?'),
                                           ', '.join(snapshot.get('sports_list', [])))
        + '  Total ligas    : %s\n' % snapshot.get('total_leagues', '?')
        + '  Total temporadas: %s\n' % snapshot.get('total_seasons', '?')
        + '  Total partidos : %s\n' % snapshot.get('total_matches', '?')
        + '  Total equipos  : %s\n' % snapshot.get('total_teams', '?')
        + '  Total noticias : %s\n' % snapshot.get('total_news', '?')
        + '  Total jugadores: %s\n' % snapshot.get('total_players', '?')
    )


def comparison_text(idx: int) -> dict:
    """Texto de la comparación snapshot[idx] vs snapshot[idx-1], tal cual el script.
    Para idx=0 (sin anterior) muestra el bloque 'Primer snapshot'."""
    history = db_history.load_history()
    n = len(history)
    if n == 0:
        return {'idx': idx, 'timestamp': None, 'total': 0, 'text': 'No hay historial guardado aún.'}
    if idx < 0:
        idx = 0
    if idx >= n:
        idx = n - 1
    curr = history[idx]
    buf = io.StringIO()
    with redirect_stdout(buf):
        if idx == 0:
            print(_first_snapshot_text(curr))
        else:
            db_history.show_comparison(history[idx - 1], curr)
    return {'idx': idx, 'timestamp': curr.get('timestamp'), 'total': n, 'text': buf.getvalue()}


def take_snapshot() -> dict:
    """Toma un snapshot NUEVO (consulta el remoto — solo SELECT) y lo agrega al historial.
    Devuelve el texto de la comparación contra el anterior y el nuevo índice."""
    history  = db_history.load_history()
    snapshot = db_history.get_snapshot()          # ← consulta remota (autorizada)
    buf = io.StringIO()
    with redirect_stdout(buf):
        if history:
            db_history.show_comparison(history[-1], snapshot)
        else:
            print(_first_snapshot_text(snapshot))
    history.append(snapshot)
    db_history.save_history(history)
    return {'idx': len(history) - 1, 'timestamp': snapshot.get('timestamp'),
            'total': len(history), 'text': buf.getvalue()}


# ── Estado por liga desde los logs ──────────────────────────────────────────────

_TS_RE   = re.compile(r'update_matches_(\d{8})_(\d{6})\.log$')
_HEAD_RE = re.compile(r'^\[([A-Z._]+)\]\s+(.+?)\s+—\s+\d+\s+partidos\s*$')
_COV_RE  = re.compile(r'\[COBERTURA\s+(.+?)\]\s+encontrados\s+(\d+)\s+/\s+(\d+)\s+en DB')
_WARN_RE = re.compile(r'ADVERTENCIA:\s+NO se encontraron todos\s+\(faltan\s+(\d+)\)')
_OK_RE   = re.compile(r'OK:\s+todos los partidos encontrados')


def _ts_from_name(path: str):
    m = _TS_RE.search(os.path.basename(path))
    if not m:
        return None, None
    try:
        dt = datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S')
        return dt, dt.strftime('%Y-%m-%d %H:%M')
    except ValueError:
        return None, None


def _parse_log(path: str) -> dict:
    """Devuelve {league_key: {sport, encontrados, total, estado}} de UN log.
    La cobertura final de cada liga es la última línea [COBERTURA ...] suya."""
    leagues = {}
    cur_key = None
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                mh = _HEAD_RE.match(line.rstrip())
                if mh:
                    cur_key = mh.group(2).strip()
                    leagues.setdefault(cur_key, {
                        'sport': mh.group(1), 'encontrados': None, 'total': None, 'estado': '—'})
                    continue
                mc = _COV_RE.search(line)
                if mc:
                    key = mc.group(1).strip()
                    rec = leagues.setdefault(key, {'sport': '', 'encontrados': None,
                                                   'total': None, 'estado': '—'})
                    rec['encontrados'] = int(mc.group(2))
                    rec['total']       = int(mc.group(3))
                    continue
                mw = _WARN_RE.search(line)
                if mw and cur_key in leagues:
                    leagues[cur_key]['estado'] = 'faltan %s' % mw.group(1)
                    continue
                if _OK_RE.search(line) and cur_key in leagues:
                    leagues[cur_key]['estado'] = 'OK (todos encontrados)'
    except OSError:
        pass
    return leagues


def leagues_status_from_logs() -> list[dict]:
    """Estado por liga: recorre todos los logs update_matches_*.log de más reciente a
    más antiguo y se queda con la PRIMERA aparición de cada liga (= su última ejecución)."""
    logs = glob.glob(os.path.join(LOGS_DIR, 'update_matches_*.log'))
    # ordenar por timestamp del nombre, descendente (más reciente primero)
    logs_dt = []
    for p in logs:
        dt, label = _ts_from_name(p)
        if dt:
            logs_dt.append((dt, label, p))
    logs_dt.sort(key=lambda x: x[0], reverse=True)

    seen = {}
    for dt, label, path in logs_dt:
        for key, rec in _parse_log(path).items():
            if key in seen:
                continue   # ya tenemos una ejecución más reciente de esta liga
            cov = ('encontrados %d / %d en DB' % (rec['encontrados'], rec['total'])
                   if rec['encontrados'] is not None else '—')
            seen[key] = {
                'liga':        key,
                'sport':       rec['sport'],
                'last_run':    label,
                'cobertura':   cov,
                'encontrados': rec['encontrados'],
                'total':       rec['total'],
                'estado':      rec['estado'],
            }
    return sorted(seen.values(), key=lambda r: r['last_run'], reverse=True)
