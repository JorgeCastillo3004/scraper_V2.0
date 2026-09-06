"""¿Qué pasa con el perfil si el navegador NO cierra limpio (kill -9, reboot,
systemd matando el servicio)? Es el caso real del servidor.

Abre un navegador sobre el perfil A, lo mata a lo bruto (queda el `lock` colgado) y
vuelve a abrir sobre el MISMO perfil para ver si Firefox descarta el lock huérfano y
si la sesión sobrevivió al cierre sucio.

  sports_env/bin/python scripts/_debug_perfil_lock_stale.py [--headless]
"""
import sys, os, time, signal, argparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, 'src'), os.path.join(_ROOT, 'scripts')]

from common_functions import launch_navigator, is_logged_in, FS_URL

ap = argparse.ArgumentParser()
ap.add_argument('--headless', action='store_true')
args = ap.parse_args()

PERFIL = os.path.join(_ROOT, 'tmp', 'profiles', 'live_a')

print('=== 1) abrir sobre el perfil A y MATAR el navegador a lo bruto ===')
d = launch_navigator(FS_URL, headless=args.headless, lightweight=True, profile_dir=PERFIL)
print('  logueado:', is_logged_in(d, 8))
pid = d.service.process.pid                       # geckodriver
hijos = [int(x) for x in os.popen(f'pgrep -P {pid}').read().split()]
os.kill(pid, signal.SIGKILL)
for h in hijos:
    try:
        os.kill(h, signal.SIGKILL)
    except Exception:
        pass
time.sleep(3)
print('  matado (SIGKILL) — lock presente:', os.path.exists(os.path.join(PERFIL, 'lock')))

print('\n=== 2) reabrir sobre el MISMO perfil (lock huérfano) ===')
try:
    t0 = time.time()
    d2 = launch_navigator(FS_URL, headless=args.headless, lightweight=True, profile_dir=PERFIL)
    print(f'  abrió igual en {time.time()-t0:.1f}s → Firefox descarta el lock huérfano')
    print('  sesión sobrevivió al cierre sucio:', is_logged_in(d2, 8))
    d2.quit()
except Exception as e:
    print(f'  NO abrió: {type(e).__name__}: {str(e)[:160]}')
    print('  → habría que borrar el lock antes de reusar el perfil')
