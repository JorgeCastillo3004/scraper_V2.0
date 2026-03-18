"""
sync_checkpoints.py

Sincroniza los archivos de checkpoints de ligas entre local y servidor remoto.
Lógica: solo añade archivos faltantes en cada lado — nunca sobreescribe.

Carpetas sincronizadas:
  check_points/results/
  check_points/fixtures/
  check_points/leagues_season/

Uso:
  source /home/you/env/sports_env/bin/activate
  python scripts/sync_checkpoints.py
"""

import os
import sys
import io
import paramiko
from rich.console import Console
from rich.table import Table
from rich.text import Text

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import SERVER_HOST, SERVER_USER, SERVER_PASS, SERVER_PATH

LOCAL_BASE  = '/home/you/work_2026/scraper_V2.0'
REMOTE_BASE = SERVER_PATH

SYNC_DIRS = [
    'check_points/results',
    'check_points/fixtures',
    'check_points/leagues_season',
]

console = Console()


# ── SFTP helpers ───────────────────────────────────────────────────────────────

def sftp_listdir(sftp, remote_path):
    """Lista archivos en remote_path. Retorna set vacío si no existe."""
    try:
        return set(sftp.listdir(remote_path))
    except FileNotFoundError:
        return set()


def sftp_makedirs(sftp, path):
    """Crea directorios remotos recursivamente."""
    parts = [p for p in path.split('/') if p]
    current = ''
    for part in parts:
        current += '/' + part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def remote_walk(sftp, remote_dir):
    """
    Genera (remote_dirpath, [filenames]) recursivamente,
    análogo a os.walk pero sobre SFTP.
    """
    try:
        entries = sftp.listdir_attr(remote_dir)
    except FileNotFoundError:
        return

    files = []
    subdirs = []
    for entry in entries:
        if entry.st_mode & 0o170000 == 0o040000:  # es directorio
            subdirs.append(entry.filename)
        else:
            files.append(entry.filename)

    yield remote_dir, files

    for subdir in subdirs:
        yield from remote_walk(sftp, remote_dir + '/' + subdir)


# ── Recopilación de diferencias ────────────────────────────────────────────────

def collect_diff(sftp):
    """
    Recorre todas las carpetas de sync y calcula:
      - to_upload: archivos presentes en local pero no en servidor
      - to_download: archivos presentes en servidor pero no en local

    Retorna (to_upload, to_download) donde cada elemento es
    lista de (local_path, remote_path).
    """
    to_upload   = []
    to_download = []

    for sync_dir in SYNC_DIRS:
        local_root  = os.path.join(LOCAL_BASE, sync_dir)
        remote_root = REMOTE_BASE + '/' + sync_dir

        if not os.path.exists(local_root):
            # Carpeta local no existe → solo descargar desde servidor
            for remote_dir, files in remote_walk(sftp, remote_root):
                rel = remote_dir[len(remote_root):].lstrip('/')
                for fname in files:
                    remote_path = remote_dir + '/' + fname
                    local_path  = os.path.join(local_root, rel, fname) if rel else os.path.join(local_root, fname)
                    to_download.append((local_path, remote_path))
            continue

        # Recorrer árbol local
        for dirpath, dirnames, filenames in os.walk(local_root):
            dirnames.sort()
            rel         = os.path.relpath(dirpath, local_root)
            remote_dir  = (remote_root + '/' + rel.replace(os.sep, '/')) if rel != '.' else remote_root

            remote_files = sftp_listdir(sftp, remote_dir)
            local_files  = set(filenames)

            # Archivos solo en local → subir
            for fname in sorted(local_files - remote_files):
                to_upload.append((
                    os.path.join(dirpath, fname),
                    remote_dir + '/' + fname,
                ))

            # Archivos solo en servidor → bajar
            for fname in sorted(remote_files - local_files):
                to_download.append((
                    os.path.join(dirpath, fname),
                    remote_dir + '/' + fname,
                ))

        # Recorrer árbol remoto para detectar carpetas que no existen en local
        for remote_dir, files in remote_walk(sftp, remote_root):
            rel        = remote_dir[len(remote_root):].lstrip('/')
            local_dir  = os.path.join(local_root, rel.replace('/', os.sep)) if rel else local_root
            if os.path.exists(local_dir):
                continue  # ya procesado arriba
            for fname in files:
                remote_path = remote_dir + '/' + fname
                local_path  = os.path.join(local_dir, fname)
                to_download.append((local_path, remote_path))

    return to_upload, to_download


# ── Presentación de resumen ────────────────────────────────────────────────────

def _league_label(path):
    """Extrae 'carpeta/archivo' para mostrar en tabla."""
    parts = path.replace(LOCAL_BASE, '').replace(REMOTE_BASE, '').replace('\\', '/').lstrip('/')
    # Tomar las últimas 3 partes: dir_raiz/liga/archivo
    segments = parts.split('/')
    return '/'.join(segments[-3:]) if len(segments) >= 3 else parts


def show_summary(to_upload, to_download):
    """Muestra tabla de cambios y pide confirmación."""
    if not to_upload and not to_download:
        console.print('\n[green]  Todo sincronizado — no hay diferencias.[/green]\n')
        return False

    table = Table(title='Resumen de sincronización', show_header=True, show_lines=False)
    table.add_column('Dirección', style='bold', justify='center', width=12)
    table.add_column('Archivo', no_wrap=False)

    MAX_ROWS = 40  # limitar para no llenar la pantalla

    shown = 0
    for local_p, remote_p in to_upload[:MAX_ROWS]:
        table.add_row('[cyan]↑ LOCAL→SRV[/cyan]', _league_label(local_p))
        shown += 1

    for local_p, remote_p in to_download[:max(0, MAX_ROWS - shown)]:
        table.add_row('[yellow]↓ SRV→LOCAL[/yellow]', _league_label(remote_p))

    console.print()
    console.print(table)

    extra_upload   = max(0, len(to_upload)   - MAX_ROWS)
    extra_download = max(0, len(to_download) - max(0, MAX_ROWS - len(to_upload)))
    if extra_upload or extra_download:
        console.print(f'  [dim]... y {extra_upload + extra_download} archivo(s) más[/dim]')

    console.print()
    console.print(f'  [cyan]↑ Subir al servidor:[/cyan]  {len(to_upload):>4} archivos')
    console.print(f'  [yellow]↓ Bajar a local:   [/yellow]  {len(to_download):>4} archivos')
    console.print()

    resp = input('  ¿Ejecutar sincronización? [s/N]: ').strip().lower()
    return resp == 's'


# ── Ejecución de transferencias ────────────────────────────────────────────────

def execute_sync(sftp, to_upload, to_download):
    errors = []

    # Subir archivos locales al servidor
    if to_upload:
        console.print(f'\n[cyan]  Subiendo {len(to_upload)} archivo(s)...[/cyan]')
        for local_p, remote_p in to_upload:
            try:
                sftp_makedirs(sftp, os.path.dirname(remote_p))
                sftp.put(local_p, remote_p)
                console.print(f'  [dim]↑ {_league_label(local_p)}[/dim]')
            except Exception as e:
                errors.append(f'↑ {local_p}: {e}')

    # Bajar archivos del servidor a local
    if to_download:
        console.print(f'\n[yellow]  Bajando {len(to_download)} archivo(s)...[/yellow]')
        for local_p, remote_p in to_download:
            try:
                os.makedirs(os.path.dirname(local_p), exist_ok=True)
                sftp.get(remote_p, local_p)
                console.print(f'  [dim]↓ {_league_label(remote_p)}[/dim]')
            except Exception as e:
                errors.append(f'↓ {remote_p}: {e}')

    return errors


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    console.print('\n[bold]Conectando al servidor...[/bold]')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER_HOST, username=SERVER_USER, password=SERVER_PASS)
    sftp = client.open_sftp()

    console.print('[dim]  Analizando diferencias...[/dim]')
    to_upload, to_download = collect_diff(sftp)

    if not show_summary(to_upload, to_download):
        console.print('[yellow]  Sincronización cancelada.[/yellow]\n')
        sftp.close()
        client.close()
        return

    errors = execute_sync(sftp, to_upload, to_download)

    sftp.close()
    client.close()

    console.print()
    if errors:
        console.print(f'[red]  Errores ({len(errors)}):[/red]')
        for e in errors:
            console.print(f'  [red]  {e}[/red]')
    else:
        console.print('[green]  Sincronización completada sin errores ✓[/green]')
    console.print()


if __name__ == '__main__':
    main()
