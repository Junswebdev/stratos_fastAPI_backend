from fastapi import WebSocket
from typing import Dict, List
from uuid import UUID
import asyncio

class ConnectionManager:
    def __init__(self):
        # Active connections: user_id -> List[WebSocket]
        self.active_connections: Dict[UUID, List[WebSocket]] = {}
        self._lock = asyncio.Lock()
    
    async def connect(self, user_id: UUID, websocket: WebSocket):
        """Add a connection to the manager. Note: accept() must be called before this."""
        async with self._lock:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = []
            self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: UUID, websocket: WebSocket):
        if user_id in self.active_connections:
            try:
                self.active_connections[user_id].remove(websocket)
            except ValueError:
                pass  # Already removed
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, message: dict, user_id: UUID):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    # Connection might be closed, it will be cleaned up by disconnect
                    pass

    async def broadcast(self, message: dict, user_ids: List[UUID]):
        for user_id in user_ids:
            await self.send_personal_message(message, user_id)

manager = ConnectionManager()
