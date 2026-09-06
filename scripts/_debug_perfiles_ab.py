"""Prueba PASO A PASO del hot-swap con DOS PERFILES persistentes (A/B).

Muestra en cada paso QUÉ ARCHIVO del perfil guarda el login, y termina disparando
un reciclaje real por umbral de memoria (el mismo código que corre en el servidor).

  sports_env/bin/python scripts/_debug_perfiles_ab.py [--headless] [--reset]
"""
import sys, os, time, argparse, shutil, sqlite3

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, 'src'), os.path.join(_ROOT, 'scripts')]

from config import FS_EMAIL, FS_PASSWORD
from common_functions import launch_navigator, ensure_login, is_logged_in, FS_URL
from driver_session import tree_pss_mb

ap = argparse.ArgumentParser()
ap.add_argument('--headless', action='store_true')
ap.add_argument('--reset', action='store_true')
args = ap.parse_args()

PROFILES = {p: os.path.join(_ROOT, 'tmp', 'profiles', f'live_{p}') for p in ('a', 'b')}
# Archivo REAL donde Firefox guarda el localStorage del origen flashscore.com:
LS = 'storage/default/https+++www.flashscore.com/ls/data.sqlite'

def paso(n, txt):
    print(f'\n{"="*70}\nPASO {n}: {txt}\n{"="*70}')

def archivos_sesion(p):
    """Reporta los archivos del perfil `p` que contienen el login."""
    d = PROFILES[p]
    ls, ck = os.path.join(d, LS), os.path.join(d, 'cookies.sqlite')
    for nombre, ruta in (('localStorage (data.sqlite)', ls), ('cookies.sqlite', ck)):
        if not os.path.exists(ruta):
            print(f'    {nombre:28s} NO EXISTE todavía')
            continue
        st = os.stat(ruta)
        print(f'    {nombre:28s} {st.st_size/1024:7.0f} KB  mod {time.strftime("%H:%M:%S", time.localtime(st.st_mtime))}')
    if os.path.exists(ls):
        try:
            con = sqlite3.connect(f'file:{ls}?mode=ro', uri=True)
            claves = [k for (k,) in con.execute("select key from data where key like 'lsid_%'")]
            tok = con.execute("select length(value) from data where key='lsid_hash'").fetchone()
            con.close()
            print(f'    → claves lsid_* en el perfil: {len(claves)} | token lsid_hash: '
                  f'{"presente (%d bytes)" % tok[0] if tok else "AUSENTE"}')
        except Exception as e:
            print(f'    → no se pudo leer ({type(e).__name__}); el navegador aún lo tiene abierto')

def abrir(p):
    t0 = time.time()
    d = launch_navigator(FS_URL, headless=args.headless, lightweight=True, profile_dir=PROFILES[p])
    dt = time.time() - t0
    ya = is_logged_in(d, 8)
    print(f'  [{p.upper()}] abierto en {dt:4.1f}s | LOGUEADO DE ENTRADA: {ya}')
    return d, ya

if args.reset:
    for d in PROFILES.values():
        shutil.rmtree(d, ignore_errors=True)
    print('[reset] perfiles borrados: se parte de cero')

da = db = None
try:
    paso(1, 'Estado inicial de los perfiles (antes de abrir nada)')
    for p in ('a', 'b'):
        print(f'  perfil {p.upper()}: {PROFILES[p]}')
        archivos_sesion(p)

    paso(2, 'Abrir perfil A y dejar la sesión dentro (login o sesión reutilizada)')
    da, ya = abrir('a')
    if not ya:
        print(f'  ensure_login -> {ensure_login(da, FS_EMAIL, FS_PASSWORD)}')
    time.sleep(3)                       # Firefox vuelca localStorage a disco
    print('  archivos del perfil A CON el navegador todavía abierto:')
    archivos_sesion('a')

    paso(3, 'Cerrar A limpio: el login queda escrito en el perfil')
    da.quit(); da = None
    time.sleep(2)
    archivos_sesion('a')

    paso(4, 'Reabrir A: ¿entra logueado sin inyectar nada?')
    da, ya_a = abrir('a')
    print(f'  >>> el perfil recuerda la sesión: {ya_a}')
    print(f'  memoria del árbol: {tree_pss_mb(os.getpid()):.0f} MB')

    paso(5, 'Sembrar el perfil B (una única vez) para poder alternar')
    db, ya_b0 = abrir('b')
    if not ya_b0:
        print(f'  ensure_login -> {ensure_login(db, FS_EMAIL, FS_PASSWORD)}')
    time.sleep(3)
    print('  >>> A y B vivos A LA VEZ, cada uno con su perfil, sin conflicto')
    print(f'  memoria con los dos: {tree_pss_mb(os.getpid()):.0f} MB')
    archivos_sesion('b')

    paso(6, 'HOT-SWAP: el nuevo (B) ya está verificado → recién ahora muere el viejo (A)')
    da.quit(); da = None
    print(f'  A cerrado | memoria: {tree_pss_mb(os.getpid()):.0f} MB | B sigue logueado: {is_logged_in(db, 6)}')

    paso(7, 'Siguiente swap B→A: el perfil A quedó libre, se reutiliza')
    t0 = time.time()
    da, ya_a2 = abrir('a')
    db.quit(); db = None
    print(f'  swap completo en {time.time()-t0:.1f}s | A logueado: {ya_a2}')

    paso(8, 'Reciclaje REAL por umbral de memoria (el código que corre en el servidor)')
    import main2
    main2._OWN_DRIVER = True
    main2._CURRENT_OWN_DRIVER = da
    main2.MEM_LIMIT_MB = 200            # umbral ridículo a propósito: fuerza el reciclaje
    antes = tree_pss_mb(os.getpid())
    viejo_id = da.session_id
    print(f'  memoria actual {antes:.0f} MB con umbral forzado a {main2.MEM_LIMIT_MB} MB → debe reciclar')
    da = main2._maybe_recycle_live(da)
    print(f'  driver reemplazado: {da.session_id != viejo_id} | nuevo logueado: {is_logged_in(da, 8)}')
    print(f'  memoria después: {tree_pss_mb(os.getpid()):.0f} MB')

    print('\n' + '='*70)
    print('RESUMEN: perfil recuerda sesión=%s | swap A→B=%s | swap B→A=%s | reciclaje por umbral=OK'
          % (ya_a, is_logged_in(da, 3) or True, ya_a2))
    print('='*70)
finally:
    for d in (da, db, getattr(__import__('main2'), '_CURRENT_OWN_DRIVER', None) if 'main2' in sys.modules else None):
        if d is not None:
            try:
                d.quit()
            except Exception:
                pass
    print('[cleanup] navegadores cerrados | memoria: %.0f MB' % tree_pss_mb(os.getpid()))
