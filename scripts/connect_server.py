"""
Conecta al servidor remoto y abre una sesión SSH interactiva.

Uso:
    source /home/you/env/sports_env/bin/activate
    python scripts/connect_server.py
"""

import os
import sys
import select
import termios
import tty

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import SERVER_HOST, SERVER_USER
from server_conn import get_ssh_client


def main():
    print(f"Conectando a {SERVER_USER}@{SERVER_HOST}...")

    client = get_ssh_client()

    channel = client.invoke_shell(term='xterm-256color', width=220, height=50)
    print("Conexión establecida. Escribe 'exit' para salir.\n")

    old_tty = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno())
        channel.settimeout(0.0)

        while True:
            r, _, _ = select.select([channel, sys.stdin], [], [])
            if channel in r:
                data = channel.recv(1024)
                if not data:
                    break
                sys.stdout.buffer.write(data)
                sys.stdout.flush()
            if sys.stdin in r:
                data = sys.stdin.read(1)
                if not data:
                    break
                channel.send(data)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)

    client.close()
    print("\nConexión cerrada.")


if __name__ == '__main__':
    main()
