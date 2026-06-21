from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, conversation_id: str, websocket: WebSocket, subprotocol: str | None = None) -> None:
        await websocket.accept(subprotocol=subprotocol)
        self.rooms[conversation_id].append(websocket)

    def disconnect(self, conversation_id: str, websocket: WebSocket) -> None:
        if websocket in self.rooms.get(conversation_id, []):
            self.rooms[conversation_id].remove(websocket)
        if not self.rooms.get(conversation_id):
            self.rooms.pop(conversation_id, None)

    async def broadcast(self, conversation_id: str, payload: dict, exclude: WebSocket | None = None) -> None:
        stale: list[WebSocket] = []
        for connection in list(self.rooms.get(conversation_id, [])):
            if connection is exclude:
                continue
            try:
                await connection.send_json(payload)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(conversation_id, connection)


manager = ConnectionManager()
