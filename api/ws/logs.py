import asyncio
import glob
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.config import LOGS_DIR

router = APIRouter()


def _latest_log(section: str):
    """Archivo de log más reciente de la sección (process_manager los nombra
    `{section}_{timestamp}.log`)."""
    files = glob.glob(os.path.join(LOGS_DIR, f'{section}_*.log'))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _tail_lines(path: str, n: int = 400, maxbytes: int = 200_000):
    """Últimas n líneas leyendo solo el final del archivo (eficiente en logs grandes)."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - maxbytes))
            data = f.read().decode('utf-8', 'replace')
        return data.splitlines()[-n:]
    except Exception:
        return []


@router.websocket("/ws/{section}/logs")
async def stream_logs(websocket: WebSocket, section: str):
    """Streamea los logs de la sección haciendo TAIL del archivo de log en disco.

    File-based a propósito: así el panel sigue cargando los logs aunque el proceso
    haya sido lanzado por OTRA instancia de la API (p.ej. tras reiniciar la API, el
    `live` sobrevive y su log se sigue escribiendo). Antes leía solo el buffer en
    memoria del process_manager, que se pierde al reiniciar → el panel quedaba vacío.
    """
    await websocket.accept()
    path = _latest_log(section)
    try:
        if not path:
            # Sin log todavía: esperar a que aparezca uno.
            while not path:
                await asyncio.sleep(1.0)
                path = _latest_log(section)

        # 1) Enviar el tail histórico al conectar.
        for ln in _tail_lines(path):
            await websocket.send_text(ln)

        # 2) Seguir el archivo (tail -f), reabriendo si rota a uno más nuevo.
        f = open(path, errors='replace')
        f.seek(0, 2)
        while True:
            ln = f.readline()
            if ln:
                await websocket.send_text(ln.rstrip('\n'))
                continue
            # ¿rotó a un log más nuevo? (nueva corrida de la sección)
            newp = _latest_log(section)
            if newp and newp != path:
                f.close()
                path = newp
                f = open(path, errors='replace')
                for ln in _tail_lines(path):
                    await websocket.send_text(ln)
                f.seek(0, 2)
                continue
            await asyncio.sleep(0.8)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            f.close()
        except Exception:
            pass
