"""Prueba del hot-swap del driver PROPIO (modo standalone del servidor):
levanta un driver, mide, fuerza el reciclaje y comprueba que el driver nuevo
queda logueado SIN formulario y que el viejo muere. Drivers propios de prueba.

  sports_env/bin/python scripts/_debug_hotswap_own.py
"""
import sys, os, time
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, 'src'), os.path.join(_ROOT, 'scripts')]

import main2
from common_functions import is_logged_in
from driver_session import tree_pss_mb

d = None
try:
    print('=== driver inicial (arranque en frío, sesión de disco) ===')
    t0 = time.time()
    d = main2._launch_own_driver()
    print(f'  listo en {time.time()-t0:.1f}s | logueado: {is_logged_in(d, 6)}')
    viejo_id = d.session_id
    print(f'  memoria árbol propio: {tree_pss_mb(os.getpid()):.0f} MB')

    print('\n=== hot-swap forzado ===')
    t0 = time.time()
    nuevo = main2._hotswap_own_driver(d)
    dt = time.time() - t0
    print(f'  hot-swap en {dt:.1f}s')
    print(f'  driver distinto: {nuevo.session_id != viejo_id}')
    print(f'  nuevo logueado : {is_logged_in(nuevo, 6)}')
    print(f'  memoria ahora  : {tree_pss_mb(os.getpid()):.0f} MB')
    try:
        d.current_url
        print('  viejo: SIGUE VIVO  ← mal, debería estar cerrado')
    except Exception as e:
        print(f'  viejo: cerrado ({type(e).__name__})')
    print(f'  _CURRENT_OWN_DRIVER apunta al nuevo: {main2._CURRENT_OWN_DRIVER is nuevo}')
    d = nuevo
finally:
    print('\n[cleanup]')
    main2._close_own_driver(d)
    print('  memoria tras cerrar: %.0f MB' % tree_pss_mb(os.getpid()))
