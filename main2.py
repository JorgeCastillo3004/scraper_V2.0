import sys
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'src'))

from config import FS_EMAIL, FS_PASSWORD

from datetime import datetime
import argparse
import time
import json
from common_functions import *
from data_base import *
from milestone7 import *

# ── Control de ejecución (pause / stop) ───────────────────────────────────────
_LOGS_DIR     = os.path.join(_ROOT, 'logs')
_CONTROL_FILE = os.path.join(_LOGS_DIR, 'run_control_live.json')
_STATUS_FILE  = os.path.join(_LOGS_DIR, 'run_status_live.json')


def _write_control(command: str):
    os.makedirs(_LOGS_DIR, exist_ok=True)
    try:
        with open(_CONTROL_FILE, 'w', encoding='utf-8') as f:
            json.dump({'command': command}, f)
    except Exception:
        pass


def _read_control() -> str:
    try:
        with open(_CONTROL_FILE, encoding='utf-8') as f:
            return json.load(f).get('command', 'none')
    except Exception:
        return 'none'


def _write_status(state: str, sports: list = None, interval: int = None):
    os.makedirs(_LOGS_DIR, exist_ok=True)
    try:
        with open(_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'state':      state,
                'sports':     sports or [],
                'interval':   interval,
                'updated_at': datetime.now().isoformat(),
            }, f)
    except Exception:
        pass


def _check_control(driver=None):
    """
    Comprueba el archivo de control en cada iteración del loop.
    - 'stop'  → cierra driver y lanza SystemExit
    - 'pause' → espera en bucle hasta recibir 'resume' o 'stop'
    - 'none'  → continúa normalmente
    """
    cmd = _read_control()

    if cmd == 'stop':
        print('[INFO] Comando stop recibido — cerrando limpiamente...')
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        _write_status('stopped')
        _write_control('none')
        raise SystemExit('Stop solicitado')

    if cmd == 'pause':
        print('[INFO] Pausado — esperando reanudación...')
        _write_status('paused')
        while True:
            time.sleep(2)
            cmd = _read_control()
            if cmd == 'resume':
                _write_control('none')
                _write_status('running')
                print('[INFO] Reanudado.')
                break
            if cmd == 'stop':
                print('[INFO] Stop durante pausa — cerrando...')
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                _write_status('stopped')
                _write_control('none')
                raise SystemExit('Stop solicitado durante pausa')


# ── Loop principal ─────────────────────────────────────────────────────────────

def main_live(sports: list, interval: int):
    print(f"[INFO] Iniciando live scraper...")
    print(f"[INFO] Deportes seleccionados: {', '.join(sports)}")
    print(f"[INFO] Intervalo entre ciclos: {interval}s")
    retry_count = 0
    MAX_RETRIES = 10
    RETRY_DELAY = 30

    _write_control('none')
    _write_status('running', sports, interval)

    while True:
        driver = None
        try:
            _check_control()

            print("[INFO] Lanzando navegador (headless Chrome)...")
            driver = launch_navigator('https://www.flashscore.com', headless=False)
            print("[INFO] Navegador listo — iniciando login...")
            login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
            print("[INFO] Login completado — comenzando ciclo live...")
            retry_count = 0

            _check_control(driver)
            _write_status('running', sports, interval)

            live_games(
                driver,
                list_sports=sports,
                interval=interval,
                check_control=_check_control,
            )

        except SystemExit:
            break

        except Exception as e:
            retry_count += 1
            print(f'[ERROR] main_live crash (intento {retry_count}/{MAX_RETRIES}): {type(e).__name__}: {e}')
            if retry_count >= MAX_RETRIES:
                print(f'[ERROR] main_live detenido tras {MAX_RETRIES} crashes consecutivos.')
                _write_status('error', sports, interval)
                break
            print(f'[INFO] Reiniciando en {RETRY_DELAY}s...')
            for _ in range(RETRY_DELAY // 2):
                time.sleep(2)
                try:
                    _check_control()
                except SystemExit:
                    return

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    _write_status('stopped')
    print('[INFO] main_live finalizado.')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Live scraper — milestone7')
    parser.add_argument(
        '--sports', nargs='+',
        default=['FOOTBALL'],
        help='Lista de deportes a procesar, e.g. --sports FOOTBALL BASKETBALL',
    )
    parser.add_argument(
        '--interval', type=int,
        default=60,
        help='Segundos entre ciclos de actualización (default: 60)',
    )
    args = parser.parse_args()
    main_live(sports=args.sports, interval=args.interval)
