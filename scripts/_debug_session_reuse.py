"""Prueba: ¿se puede abrir un driver YA logueado, sin pasar por el formulario?

Fase 1 — driver A: login normal (formulario) y guardar cookies+localStorage en
         tmp/fs_session.json.
Fase 2 — driver B: navegador nuevo + inyectar esa sesión → verificar que entra
         logueado SIN formulario. Es el caso del hot-swap del live.

Mide cuánto cuesta cada camino. Usa drivers PROPIOS de prueba (no toca el driver del
panel ni el Firefox de escritorio); los cierra al terminar salvo --keep.

  sports_env/bin/python scripts/_debug_session_reuse.py [--no-headless] [--keep]
"""
import sys, os, time, argparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, 'src'), os.path.join(_ROOT, 'scripts')]

from config import FS_EMAIL, FS_PASSWORD
from common_functions import (launch_navigator, ensure_login, is_logged_in,
                              save_fs_session, load_fs_session, apply_fs_session,
                              FS_URL, FS_SESSION_FILE)

ap = argparse.ArgumentParser()
ap.add_argument('--no-headless', dest='headless', action='store_false')
ap.add_argument('--keep', action='store_true', help='no cerrar los drivers al terminar')
ap.set_defaults(headless=True)
args = ap.parse_args()

a = b = None
try:
    # ── Fase 1: login por formulario ─────────────────────────────────────────
    print('\n=== FASE 1: driver A (login por formulario) ===')
    t0 = time.time()
    a = launch_navigator(FS_URL, headless=args.headless, lightweight=True)
    t_open = time.time() - t0
    print(f'  navegador abierto en {t_open:.1f}s — logueado de entrada: {is_logged_in(a, 5)}')

    t0 = time.time()
    modo = ensure_login(a, FS_EMAIL, FS_PASSWORD)
    t_login = time.time() - t0
    print(f'  ensure_login -> {modo} en {t_login:.1f}s | sesión activa: {is_logged_in(a, 5)}')

    ses = save_fs_session(a)
    print(f'  cookies guardadas: {[c["name"] for c in ses["cookies"]]}')
    print(f'  claves localStorage: {len(ses["storage"])}')

    # ── Fase 2: driver nuevo reutilizando la sesión ──────────────────────────
    print('\n=== FASE 2: driver B (sin formulario, sesión inyectada) ===')
    t0 = time.time()
    b = launch_navigator(FS_URL, headless=args.headless, lightweight=True)
    t_open_b = time.time() - t0
    print(f'  navegador abierto en {t_open_b:.1f}s — logueado de entrada: {is_logged_in(b, 5)}')

    t0 = time.time()
    ok_disco = apply_fs_session(b, load_fs_session())
    t_restore = time.time() - t0
    print(f'  restaurar desde JSON -> {ok_disco} en {t_restore:.1f}s')

    print('\n=== RESULTADO ===')
    print(f'  login por formulario : {t_login:.1f}s')
    print(f'  restaurar sesión     : {t_restore:.1f}s  (ok={ok_disco})')
    print('  VEREDICTO:', 'SE PUEDE evitar el login' if ok_disco else 'NO alcanza con cookies/localStorage')
finally:
    if not args.keep:
        for d in (b, a):
            if d is not None:
                try:
                    d.quit()
                except Exception:
                    pass
        print('\n[cleanup] drivers de prueba cerrados')
    else:
        print(f'\n[keep] drivers vivos; sesión en {FS_SESSION_FILE}')
