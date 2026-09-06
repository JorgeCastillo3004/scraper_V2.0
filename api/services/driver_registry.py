"""
Registro CENTRAL de drivers (ÍNDICE)
------------------------------------
Un solo archivo `tmp/drivers/registry.json` que cataloga TODOS los drivers del
proyecto con su identificador, rol, sesión, pid del launcher, estado y el script
que lo está usando (`owner`). Permite coordinar el acceso compartido al driver.

Es un ÍNDICE (no autoritativo): los `*_session.json` / `*_launcher.json` siguen
existiendo igual y `get_driver()` no se toca. Este registro los ESPEJA en cada
lectura (reconciliación) y persiste solo el estado de coordinación que no vive en
esos archivos: `owner`, `acquired_at`, `holder_pid`, `last_used`.

Estados (`status`):
  - `closed`  : el driver no está vivo (launcher muerto o sin sesión).
  - `ready`   : vivo y LIBRE (lo puede tomar un script).
  - `busy`    : vivo y EN USO por `owner`.

Roles:
  - `shared`  : driver compartido por los scripts no-live (corrección). Por defecto 1.
  - `live`    : driver dedicado del live (siempre marcado en uso por 'live').

NUNCA toca la BD. NUNCA mata procesos (eso lo hace driver_manager con SIGTERM).
"""

import fcntl
import json
import os
from datetime import datetime
from urllib.parse import urlparse

from api.config import PROJECT_ROOT

_TMP = os.path.join(PROJECT_ROOT, 'tmp')
_DRIVERS_DIR = os.path.join(_TMP, 'drivers')
REGISTRY_PATH = os.path.join(_DRIVERS_DIR, 'registry.json')
_LOCK_PATH = os.path.join(_DRIVERS_DIR, 'registry.lock')

# Drivers conocidos: índice de los pares de archivos que ya usa el proyecto.
# (Mientras sea ÍNDICE estos paths duplican los de driver_manager; al migrar a
#  autoritativo se unifican.)
KNOWN = {
    'correction': {
        'role': 'shared',
        'session_file':  os.path.join(_TMP, 'driver_session.json'),
        'launcher_file': os.path.join(_TMP, 'driver_launcher.json'),
    },
    'live': {
        'role': 'live',
        'session_file':  os.path.join(_TMP, 'live_driver.json'),
        'launcher_file': os.path.join(_TMP, 'live_launcher.json'),
    },
}


def _now() -> str:
    return datetime.now().isoformat()


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _load() -> dict:
    data = _read_json(REGISTRY_PATH)
    if isinstance(data, dict) and isinstance(data.get('drivers'), dict):
        return data
    return {'updated_at': None, 'drivers': {}}


def _save_atomic(data: dict):
    data['updated_at'] = _now()
    os.makedirs(_DRIVERS_DIR, exist_ok=True)
    tmp = REGISTRY_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REGISTRY_PATH)


class _FileLock:
    """Lock entre procesos para serializar acquire/release (evita carrera del
    check-then-set sobre la bandera de uso)."""
    def __init__(self):
        os.makedirs(_DRIVERS_DIR, exist_ok=True)
        self._fd = None

    def __enter__(self):
        self._fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_RDWR)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)


def _physical(driver_id: str) -> dict:
    """Estado FÍSICO leído de los archivos del driver: vivo, sesión, pid, puerto."""
    spec = KNOWN[driver_id]
    launcher = _read_json(spec['launcher_file'])
    session = _read_json(spec['session_file'])
    pid = launcher.get('pid')
    alive = (_pid_alive(pid)
             and bool(session.get('session_id'))
             and os.path.exists(spec['session_file']))
    port = None
    eu = session.get('executor_url')
    if eu:
        try:
            port = urlparse(eu if eu.startswith('http') else 'http://' + eu).port
        except Exception:
            port = None
    return {
        'alive':         bool(alive),
        'launcher_pid':  pid if _pid_alive(pid) else None,
        'session_id':    session.get('session_id'),
        'executor_url':  eu,
        'port':          port,
        'headless':      launcher.get('headless'),
        'started_at':    launcher.get('started_at'),
    }


def _reconcile(data: dict) -> dict:
    """Refresca el registro desde los archivos físicos + reclama locks muertos.
    Debe llamarse SIEMPRE dentro de _FileLock."""
    drivers = data.setdefault('drivers', {})
    for did, spec in KNOWN.items():
        phys = _physical(did)
        prev = drivers.get(did, {})
        owner       = prev.get('owner')
        acquired_at = prev.get('acquired_at')
        holder_pid  = prev.get('holder_pid')
        last_used   = prev.get('last_used')

        if not phys['alive']:
            status = 'closed'
            owner = acquired_at = holder_pid = None
        else:
            # Lock muerto: el dueño ya no existe -> liberar.
            if owner and holder_pid and not _pid_alive(holder_pid):
                owner = acquired_at = holder_pid = None
            # El live es dedicado: dueño implícito 'live' mientras viva.
            if spec['role'] == 'live' and not owner:
                owner = 'live'
            status = 'busy' if owner else 'ready'

        drivers[did] = {
            'id': did, 'role': spec['role'],
            'session_file': spec['session_file'],
            'launcher_file': spec['launcher_file'],
            'status': status,
            'owner': owner, 'acquired_at': acquired_at, 'holder_pid': holder_pid,
            'last_used': last_used,
            **phys,
        }
    return data


# ── API pública ──────────────────────────────────────────────────────────────

def list_drivers() -> dict:
    """Registro completo, reconciliado contra la realidad (read-only seguro)."""
    with _FileLock():
        data = _reconcile(_load())
        _save_atomic(data)
        return data


def available(role: str = 'shared') -> dict | None:
    """Primer driver del rol indicado que está `ready` (libre). None si no hay."""
    for d in list_drivers()['drivers'].values():
        if d['role'] == role and d['status'] == 'ready':
            return d
    return None


def acquire(owner: str, holder_pid=None, role: str = 'shared', driver_id: str = None) -> dict | None:
    """Toma un driver libre y lo marca `busy` con `owner`. Atómico (lock).
    Devuelve el dict del driver, o None si NO hay ninguno disponible (en ese caso
    el caller debe pedir confirmación al usuario para crear uno; nunca crear solo)."""
    with _FileLock():
        data = _reconcile(_load())
        drivers = data['drivers']
        cand = None
        if driver_id:
            d = drivers.get(driver_id)
            if d and d['status'] == 'ready':
                cand = driver_id
        else:
            for did, d in drivers.items():
                if d['role'] == role and d['status'] == 'ready':
                    cand = did
                    break
        if not cand:
            _save_atomic(data)
            return None
        d = drivers[cand]
        d.update(status='busy', owner=owner, acquired_at=_now(),
                 holder_pid=holder_pid, last_used=_now())
        _save_atomic(data)
        return d


def touch(driver_id: str = None, owner: str = None):
    """Refresca `last_used` del driver en uso (para que el idle-close no lo cierre
    mientras se está usando en una corrida larga)."""
    with _FileLock():
        data = _reconcile(_load())
        for did, d in data['drivers'].items():
            if (driver_id and did == driver_id) or (owner and d.get('owner') == owner):
                d['last_used'] = _now()
        _save_atomic(data)


def release(owner: str = None, driver_id: str = None) -> bool:
    """Libera el driver (lo vuelve `ready`) y registra `last_used`."""
    with _FileLock():
        data = _reconcile(_load())
        found = False
        for did, d in data['drivers'].items():
            if (driver_id and did == driver_id) or (owner and d.get('owner') == owner):
                d.update(status='ready' if d['alive'] else 'closed',
                         owner=None, acquired_at=None, holder_pid=None,
                         last_used=_now())
                found = True
        _save_atomic(data)
        return found


def idle_candidates(max_idle_seconds: float, role: str = 'shared') -> list:
    """Drivers `ready` (no en uso) ociosos > max_idle_seconds -> candidatos a cerrar
    por inactividad. El live (role != shared) queda excluido por defecto."""
    out = []
    now = datetime.now()
    for d in list_drivers()['drivers'].values():
        if d['role'] != role or d['status'] != 'ready' or not d['alive']:
            continue
        ref = d.get('last_used') or d.get('started_at')
        if not ref:
            continue
        try:
            idle = (now - datetime.fromisoformat(ref)).total_seconds()
        except Exception:
            continue
        if idle > max_idle_seconds:
            out.append({'id': d['id'], 'idle_seconds': int(idle)})
    return out
