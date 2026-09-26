"""
Shared web-gateway security helpers: optional API-key enforcement for REST
routes and WebSocket endpoints.

Auth is opt-in: when ``config.VISION_API_KEY`` is empty/unset the API stays open
for frictionless local use. Once a key is configured, every protected route and
socket must present it via the ``X-API-Key`` header or an ``api_key`` query
parameter.
"""

from typing import Optional

from fastapi import Header, HTTPException, Query, WebSocket

from vision.config import config
from vision.logger import logger


def configured_api_key() -> Optional[str]:
    """Return the configured API key, or None when auth is disabled."""
    key = getattr(config, "VISION_API_KEY", None)
    if key and str(key).strip():
        return str(key).strip()
    return None


def _matches(provided: Optional[str]) -> bool:
    expected = configured_api_key()
    if not expected:
        return True  # auth disabled
    return bool(provided) and provided.strip() == expected


async def require_api_key(
    x_api_key: Optional[str] = Header(default=None),
    api_key: Optional[str] = Query(default=None),
) -> None:
    """FastAPI dependency enforcing the API key on protected REST routes."""
    if configured_api_key() is None:
        return
    if not _matches(x_api_key or api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def verify_ws_api_key(websocket: WebSocket) -> bool:
    """Validate the API key for a WebSocket handshake before accepting it.

    Reads the ``api_key`` query parameter or ``X-API-Key`` header. Returns True
    when auth is disabled or the key matches.
    """
    if configured_api_key() is None:
        return True
    provided = websocket.query_params.get("api_key") or websocket.headers.get("x-api-key")
    ok = _matches(provided)
    if not ok:
        logger.warning("[WebSocket] Rejected connection: missing/invalid API key.")
    return ok
