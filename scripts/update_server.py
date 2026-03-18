"""
Script para sincronizar código local → servidor remoto.
- Sube solo archivos de código y carpetas relevantes
- Carpeta images: agrega solo archivos nuevos (no reemplaza existentes)
- Excluye: venv, __pycache__, notebooks, claude_memory, docs, etc.

Uso:
  source /home/you/env/sports_env/bin/activate
  python scripts/update_server.py                              # sync completo
  python scripts/update_server.py leagues_info                 # solo leagues_info.json
  python scripts/update_server.py py                           # solo archivos .py
  python scripts/update_server.py images                       # imágenes nuevas (sin reemplazar existentes)
  python scripts/update_server.py milestone4.py               # archivo raíz
  python scripts/update_server.py src/milestone4.py           # con subcarpeta
  python scripts/update_server.py milestone4.py paralel_execution.py src/data_base.py
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
LOCAL_BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
def _confirm_upload(files):
    """Muestra la lista de archivos a subir y pide confirmación al usuario.

    Args:
        files: lista de rutas relativas (str) que se van a subir.
    Returns:
        True si el usuario confirma con 's', False en caso contrario.
    """
    if not files:
        print('  Sin archivos que subir.')
        return False
    print(f'\n=== Archivos a subir ({len(files)}) ===')
    for f in files:
        print(f'  + {f}')
    resp = input(f'\n  ¿Continuar con la subida de {len(files)} archivo(s)? [s/N]: ').strip().lower()
    return resp == 's'


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
def _collect_main_files():
    """Recorre el proyecto y devuelve lista de (local_path, remote_path, rel) a subir."""
    result = []
    for item in sorted(os.listdir(LOCAL_BASE)):
        if item in ROOT_EXCLUDE or item.startswith('.'):
            continue
        local_path  = os.path.join(LOCAL_BASE, item)
        remote_path = REMOTE_BASE + '/' + item
        if os.path.isfile(local_path):
            rel = os.path.relpath(local_path, LOCAL_BASE).replace(os.sep, '/')
            result.append((local_path, remote_path, rel))
        elif os.path.isdir(local_path):
            exclude = API_SERVICE_EXCLUDE if item == 'api_service' else set()
            for root, dirs, files in os.walk(local_path):
                dirs[:] = [d for d in sorted(dirs) if d not in exclude and not d.startswith('.')]
                for fname in sorted(files):
                    fp  = os.path.join(root, fname)
                    rel = os.path.relpath(fp, LOCAL_BASE).replace(os.sep, '/')
                    result.append((fp, REMOTE_BASE + '/' + rel, rel))
    return result


def main():
    # 1. Recopilar y confirmar
    files = _collect_main_files()
    if not _confirm_upload([rel for _, _, rel in files]):
        print('  Cancelado.')
        return

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS)
    sftp = client.open_sftp()

    # 2. Subir
    print()
    for local_path, remote_path, _ in files:
        remote_makedirs(sftp, os.path.dirname(remote_path))
        upload_file(sftp, local_path, remote_path)

    sftp.close()
    client.close()
    print("\n=== Sincronización completa ✓ ===")


def upload_leagues_info():
    """Sube solo check_points/leagues_info.json al servidor."""
    local_path  = os.path.join(LOCAL_BASE, 'check_points', 'leagues_info.json')
    remote_path = REMOTE_BASE + '/check_points/leagues_info.json'

    if not _confirm_upload(['check_points/leagues_info.json']):
        print('  Cancelado.')
        return

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS)
    sftp = client.open_sftp()

    print()
    upload_file(sftp, local_path, remote_path)

    sftp.close()
    client.close()
    print('=== leagues_info.json actualizado en servidor ✓ ===\n')


def upload_specific(files):
    """Sube archivos específicos manteniendo la estructura de carpetas."""
    # Verificar existencia antes de confirmar
    valid   = [f for f in files if os.path.isfile(os.path.join(LOCAL_BASE, f))]
    missing = [f for f in files if f not in valid]
    for f in missing:
        print(f'  [skip] No encontrado: {f}')

    if not _confirm_upload(valid):
        print('  Cancelado.')
        return

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS)
    sftp = client.open_sftp()

    print()
    for f in valid:
        local_path  = os.path.join(LOCAL_BASE, f)
        remote_path = REMOTE_BASE + '/' + f.replace(os.sep, '/')
        remote_makedirs(sftp, os.path.dirname(remote_path))
        upload_file(sftp, local_path, remote_path)

    sftp.close()
    client.close()
    print('=== Archivos subidos ✓ ===')


def upload_py_files():
    """Sube solo archivos .py del proyecto (excluye check_points, images, logs, etc.)."""
    EXCLUDE_DIRS = {
        '__pycache__', '.ipynb_checkpoints', 'check_points',
        'images', 'logs', 'env', 'diagramas', 'docs', 'prueba',
    }

    # Recopilar lista antes de confirmar
    py_files = []
    for root, dirs, files in os.walk(LOCAL_BASE):
        dirs[:] = [d for d in sorted(dirs) if d not in EXCLUDE_DIRS and not d.startswith('.')]
        for fname in sorted(files):
            if fname.endswith('.py'):
                local_path = os.path.join(root, fname)
                rel = os.path.relpath(local_path, LOCAL_BASE).replace(os.sep, '/')
                py_files.append((local_path, REMOTE_BASE + '/' + rel, rel))

    if not _confirm_upload([rel for _, _, rel in py_files]):
        print('  Cancelado.')
        return

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS)
    sftp = client.open_sftp()

    print()
    for local_path, remote_path, _ in py_files:
        remote_makedirs(sftp, os.path.dirname(remote_path))
        upload_file(sftp, local_path, remote_path)

    sftp.close()
    client.close()
    print('=== Archivos .py subidos ✓ ===')


def upload_images():
    """Sube imágenes nuevas al servidor sin reemplazar las ya existentes.

    Flujo:
      1. Conecta al servidor y compara archivos locales vs remotos.
      2. Muestra lista de archivos nuevos y pide confirmación al usuario.
      3. Solo sube tras confirmar con 's'.
    """
    local_images  = os.path.join(LOCAL_BASE, 'images')
    remote_images = REMOTE_BASE + '/images'

    if not os.path.isdir(local_images):
        print(f'  [skip] Carpeta local no encontrada: {local_images}')
        return

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS)
    sftp = client.open_sftp()

    # ── 1. Detectar archivos nuevos (no existen en servidor) ──────────────────
    new_files = []
    for root, dirs, files in os.walk(local_images):
        dirs[:] = sorted(dirs)
        for fname in sorted(files):
            local_path  = os.path.join(root, fname)
            rel         = os.path.relpath(local_path, LOCAL_BASE).replace(os.sep, '/')
            remote_path = REMOTE_BASE + '/' + rel
            try:
                sftp.stat(remote_path)
                # ya existe → saltar
            except FileNotFoundError:
                new_files.append((local_path, remote_path, rel))

    # ── 2. Mostrar preview y pedir confirmación ───────────────────────────────
    if not new_files:
        print('\n  Sin imágenes nuevas que subir.')
        sftp.close()
        client.close()
        return

    print(f'\n=== Imágenes nuevas a subir ({len(new_files)}) ===')
    for _, _, rel in new_files:
        print(f'  + {rel}')

    resp = input(f'\n  ¿Subir {len(new_files)} imagen(es) nueva(s)? [s/N]: ').strip().lower()
    if resp != 's':
        print('  Cancelado.')
        sftp.close()
        client.close()
        return

    # ── 3. Subir archivos confirmados ─────────────────────────────────────────
    print()
    for local_path, remote_path, _ in new_files:
        remote_makedirs(sftp, os.path.dirname(remote_path))
        sftp.put(local_path, remote_path)
        print(f'  [upload] {remote_path}')

    sftp.close()
    client.close()
    print(f'\n=== {len(new_files)} imagen(es) subida(s) ✓ ===')


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        main()
    elif args[0] == 'leagues_info':
        upload_leagues_info()
    elif args[0] == 'py':
        upload_py_files()
    elif args[0] == 'images':
        upload_images()
    else:
        upload_specific(args)
