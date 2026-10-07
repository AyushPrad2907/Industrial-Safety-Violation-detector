import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from backend.services.alert_service import alert_service

logger = logging.getLogger(__name__)

router = APIRouter()

@router.websocket("/ws/monitor")
async def websocket_monitor_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time safety monitoring:
    Receives connection, adds to AlertService client pool,
    and streams violation events and telemetry updates.
    Handles disconnections safely without crashing the backend or AI pipeline.
    """
    await alert_service.connect(websocket)
    try:
        while True:
            # Keep-alive receive loop
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info("Client cleanly disconnected from /ws/monitor")
    except Exception as e:
        logger.warning(f"WebSocket client error: {e}")
    finally:
        alert_service.disconnect(websocket)
