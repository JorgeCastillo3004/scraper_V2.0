from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from api.services import process_manager as pm

router = APIRouter()


@router.websocket("/ws/{section}/logs")
async def stream_logs(websocket: WebSocket, section: str):
    await websocket.accept()

    state = pm.get_state(section)

    # 1. Enviar historial acumulado al cliente que acaba de conectarse
    for line in list(state.log_buffer):
        await websocket.send_text(line)

    # 2. Cola exclusiva para este cliente
    queue = pm.add_client(section)

    try:
        while True:
            line = await queue.get()

            if line == '__DONE__':
                await websocket.send_text('{"type":"status","value":"stopped"}')
                break

            await websocket.send_text(line)

    except WebSocketDisconnect:
        pass
    finally:
        pm.remove_client(section, queue)
