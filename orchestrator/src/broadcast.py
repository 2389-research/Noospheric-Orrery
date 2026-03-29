"""WebSocket broadcast for real-time viz updates.

Any search or graph interaction broadcasts entity names to all
connected viz clients, triggering the galaxy glow effect.
"""

import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect

# Connected clients
_clients: set[WebSocket] = set()


async def ws_endpoint(websocket: WebSocket):
    """WebSocket endpoint — clients subscribe to graph events."""
    await websocket.accept()
    _clients.add(websocket)
    try:
        while True:
            # Keep connection alive, ignore incoming messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        _clients.discard(websocket)


async def broadcast_search(query: str, entity_names: list[str]):
    """Broadcast search results to all connected viz clients."""
    if not _clients:
        return
    message = json.dumps({
        "type": "search_result",
        "query": query,
        "entities": entity_names,
    })
    dead = set()
    for client in _clients:
        try:
            await client.send_text(message)
        except Exception:
            dead.add(client)
    _clients -= dead


async def broadcast_entity_viewed(entity_name: str):
    """Broadcast that an entity was viewed/accessed."""
    if not _clients:
        return
    message = json.dumps({
        "type": "search_result",
        "entities": [entity_name],
    })
    dead = set()
    for client in _clients:
        try:
            await client.send_text(message)
        except Exception:
            dead.add(client)
    _clients -= dead
