"""
Script para sincronizar código local → servidor remoto.
- Sube solo archivos de código y carpetas relevantes
- Carpeta images: agrega solo archivos nuevos (no reemplaza existentes)
- Excluye: venv, __pycache__, notebooks, claude_memory, docs, etc.

Uso:
  source /home/you/env/sports_env/bin/activate
  python /home/you/work_2026/update_server.py               # sync completo
  python /home/you/work_2026/update_server.py leagues_info  # solo leagues_info.json
"""

import paramiko
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import SERVER_HOST, SERVER_USER, SERVER_PASS, SERVER_PATH

# ── Configuración ─────────────────────────────────────────────────────────────
HOST        = SERVER_HOST
USER        = SERVER_USER
PASS        = SERVER_PASS
LOCAL_BASE  = '/home/you/scraper_V2.0'
REMOTE_BASE = SERVER_PATH

# Carpetas/archivos excluidos en el nivel raíz
ROOT_EXCLUDE = {
    '__pycache__', '.ipynb_checkpoints', 'claude_memory',
    'prueba', 'diagramas', 'docs', 'images', 'logs',
    'main_depuracion.ipynb', 'env', 'scraper_V2.0',
}

# Carpetas excluidas dentro de api_service
API_SERVICE_EXCLUDE = {'venv', '__pycache__'}

# ── Helpers ────────────────────────────────────────────────────────────────────
def remote_makedirs(sftp, path):
    parts = [p for p in path.split('/') if p]
    current = ''
    for part in parts:
        current += '/' + part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)
            print(f"  [mkdir] {current}")


def upload_file(sftp, local_path, remote_path, skip_existing=False):
    if skip_existing:
        try:
            sftp.stat(remote_path)
            return  # ya existe, no reemplazar
        except FileNotFoundError:
            pass
    sftp.put(local_path, remote_path)
    print(f"  [upload] {remote_path}")


def sync_dir(sftp, local_dir, remote_dir, exclude=None, skip_existing=False):
    if exclude is None:
        exclude = set()
    for item in sorted(os.listdir(local_dir)):
        if item in exclude or item.startswith('.'):
            continue
        local_path  = os.path.join(local_dir, item)
        remote_path = remote_dir + '/' + item
        if os.path.isfile(local_path):
            upload_file(sftp, local_path, remote_path, skip_existing=skip_existing)
        elif os.path.isdir(local_path):
            remote_makedirs(sftp, remote_path)
            sync_dir(sftp, local_path, remote_path, skip_existing=skip_existing)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS)
    sftp = client.open_sftp()

    # 1. Código raíz (excluye imágenes y carpetas no-código)
    print("\n=== [1/3] Sincronizando código raíz ===")
    for item in sorted(os.listdir(LOCAL_BASE)):
        if item in ROOT_EXCLUDE or item.startswith('.'):
            continue
        local_path  = os.path.join(LOCAL_BASE, item)
        remote_path = REMOTE_BASE + '/' + item

        if os.path.isfile(local_path):
            upload_file(sftp, local_path, remote_path)
        elif os.path.isdir(local_path):
            # api_service: excluir venv
            exclude = API_SERVICE_EXCLUDE if item == 'api_service' else set()
            remote_makedirs(sftp, remote_path)
            sync_dir(sftp, local_path, remote_path, exclude=exclude)

    # 2. Imágenes — solo añadir, no reemplazar
    # print("\n=== [2/3] Sincronizando imágenes (sin reemplazar) ===")
    # local_images  = os.path.join(LOCAL_BASE, 'images')
    # remote_images = REMOTE_BASE + '/images'
    # remote_makedirs(sftp, remote_images)
    # sync_dir(sftp, local_images, remote_images, skip_existing=True)

    sftp.close()
    client.close()
    print("\n=== [3/3] Sincronización completa ✓ ===")


def upload_leagues_info():
    """Sube solo check_points/leagues_info.json al servidor."""
    local_path  = os.path.join(LOCAL_BASE, 'check_points', 'leagues_info.json')
    remote_path = REMOTE_BASE + '/check_points/leagues_info.json'

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS)
    sftp = client.open_sftp()

    print(f'\n=== Subiendo leagues_info.json ===')
    upload_file(sftp, local_path, remote_path)

    sftp.close()
    client.close()
    print('=== leagues_info.json actualizado en servidor ✓ ===\n')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'leagues_info':
        upload_leagues_info()
    else:
        main()
