"""WebSocket broadcast for real-time viz updates."""

import json
from fastapi import WebSocket, WebSocketDisconnect


class Broadcaster:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            self.clients.discard(websocket)

    async def broadcast(self, message: dict):
        if not self.clients:
            return
        data = json.dumps(message)
        dead = set()
        for client in self.clients:
            try:
                await client.send_text(data)
            except Exception:
                dead.add(client)
        self.clients -= dead


broadcaster = Broadcaster()


async def ws_endpoint(websocket: WebSocket):
    await broadcaster.connect(websocket)


async def broadcast_search(query: str, entity_names: list[str]):
    await broadcaster.broadcast({
        "type": "search_result",
        "query": query,
        "entities": entity_names,
    })


async def broadcast_entity_viewed(entity_name: str):
    await broadcaster.broadcast({
        "type": "search_result",
        "entities": [entity_name],
    })
