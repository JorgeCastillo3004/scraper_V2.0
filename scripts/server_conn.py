"""
server_conn.py — Conexión SSH/SFTP centralizada al servidor remoto.

Todos los scripts que suben/bajan archivos (update_server.py, sync_checkpoints.py,
connect_server.py) deben obtener su cliente desde aquí, para no duplicar la lógica
de autenticación.

Autenticación:
  - Si `SERVER_KEY` está definido en config y el archivo existe -> autenticación
    por CLAVE (la credencial nueva, p.ej. ssh_key/jorge_scraper_key).
  - Si no -> cae a contraseña (`SERVER_PASS`), comportamiento anterior.

Nota importante: con `look_for_keys=False` y `allow_agent=False` paramiko usa
SOLO la clave indicada y NO ofrece otras identidades del agente SSH. Esto replica
`ssh -o IdentitiesOnly=yes` y evita el error "Too many authentication failures"
que ocurre cuando el agente ofrece demasiadas claves antes de la correcta.
"""

import os
import sys

import paramiko

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import SERVER_HOST, SERVER_USER, SERVER_PASS  # noqa: E402

try:
    from config import SERVER_KEY
except ImportError:
    SERVER_KEY = ''

try:
    from config import SERVER_PORT
except ImportError:
    SERVER_PORT = 22


def get_ssh_client(timeout=15):
    """Crea y devuelve un paramiko.SSHClient ya conectado al servidor remoto.

    Usa clave privada si `SERVER_KEY` apunta a un archivo existente; de lo
    contrario usa contraseña. El llamador es responsable de cerrar el cliente.
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    key_path = os.path.expanduser(SERVER_KEY) if SERVER_KEY else ''

    if key_path and os.path.isfile(key_path):
        client.connect(
            SERVER_HOST,
            port=SERVER_PORT,
            username=SERVER_USER,
            key_filename=key_path,
            look_for_keys=False,   # equivale a IdentitiesOnly=yes
            allow_agent=False,     # no usar el agente SSH (evita "Too many auth failures")
            timeout=timeout,
        )
    else:
        client.connect(
            SERVER_HOST,
            port=SERVER_PORT,
            username=SERVER_USER,
            password=SERVER_PASS,
            timeout=timeout,
        )

    return client
