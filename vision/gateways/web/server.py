"""
FastAPI Server and WebSocket Gateway for real-time bidirectional communication.
"""

import json
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from vision.gateways.web.routes import router as api_router
from vision.gateways.web.realtime import router as realtime_router
from vision.gateways.web.security import require_api_key, verify_ws_api_key, configured_api_key
from vision.core.engine import vision_engine
from vision.core.event_bus import event_bus
from vision.constants import VisionEvents
from vision.config import config
from vision.logger import logger

app = FastAPI(title="VISION Autonomous OS", version="1.0.0")

# CORS: an explicit allow-list is required whenever credentials are enabled —
# the "*" wildcard + credentials combination is rejected by browsers. If the
# user configures "*", honour it but disable credentials to stay spec-compliant.
_origins = config.VISION_ALLOWED_ORIGINS or ["*"]
_allow_credentials = "*" not in _origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

if configured_api_key() is None:
    logger.warning(
        "[Server] VISION_API_KEY is not set — web API and WebSockets are UNAUTHENTICATED. "
        "Set VISION_API_KEY to require an X-API-Key header / ?api_key= for all /api and socket access."
    )

# Enforce the optional API key across every /api route (chat, tools/execute, memory, tasks…).
app.include_router(api_router, prefix="/api", dependencies=[Depends(require_api_key)])
app.include_router(realtime_router)


@app.on_event("startup")
async def on_startup():
    await vision_engine.initialize()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not verify_ws_api_key(websocket):
        await websocket.close(code=1008)  # policy violation
        return
    await websocket.accept()
    await event_bus.publish(VisionEvents.WEB_CLIENT_CONNECTED)
    logger.info("[WebSocket] Client connected.")

    async def push_event(data):
        try:
            await websocket.send_text(json.dumps(data))
        except Exception:
            pass

    event_bus.subscribe(VisionEvents.LLM_STREAM_CHUNK, push_event)
    event_bus.subscribe(VisionEvents.TOOL_CALL_DETECTED, push_event)
    event_bus.subscribe(VisionEvents.TOOL_EXECUTION_COMPLETED, push_event)

    try:
        while True:
            raw_data = await websocket.receive_text()
            # A single malformed frame must not tear down the whole connection —
            # skip it and keep serving the client.
            try:
                payload = json.loads(raw_data)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_text(json.dumps({"type": "error", "data": "Invalid JSON payload."}))
                continue
            if not isinstance(payload, dict):
                await websocket.send_text(json.dumps({"type": "error", "data": "Payload must be a JSON object."}))
                continue
            action = payload.get("action")

            if action == "chat":
                user_msg = payload.get("message", "")
                session_id = payload.get("session_id", "ws_session")
                synth = payload.get("synthesize_voice", True)
                response = await vision_engine.process_user_input(
                    user_text=user_msg,
                    session_id=session_id,
                    channel="web",
                    synthesize_voice=synth
                )
                await websocket.send_text(json.dumps({"type": "chat_response", "data": response}))
            elif action == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "time": json.dumps(str(raw_data))}))
    except WebSocketDisconnect:
        logger.info("[WebSocket] Client disconnected.")
    except Exception as e:
        logger.error(f"[WebSocket] Error: {e}")
    finally:
        event_bus.unsubscribe(VisionEvents.LLM_STREAM_CHUNK, push_event)
        event_bus.unsubscribe(VisionEvents.TOOL_CALL_DETECTED, push_event)
        event_bus.unsubscribe(VisionEvents.TOOL_EXECUTION_COMPLETED, push_event)
        await event_bus.publish(VisionEvents.WEB_CLIENT_DISCONNECTED)


# ── Serve Frontend Static Files ──────────────────────────────────
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent.parent / "frontend"

if FRONTEND_DIR.exists():
    @app.get("/")
    async def serve_frontend():
        """Serve the VISION dashboard SPA with fresh cache headers."""
        return FileResponse(
            str(FRONTEND_DIR / "index.html"),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

    # Mount entire frontend directory for CSS, JS, and any other static assets
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend_static")

    logger.info(f"[Server] Frontend dashboard mounted from '{FRONTEND_DIR}'")
else:
    logger.warning(f"[Server] Frontend directory not found at '{FRONTEND_DIR}' — skipping static mount.")

