# managers.py — 薄适配层
# 将原有的 ConnectionManager / GameManager 接口委托给新的 room/RoomManager。
# 保持 app.py 的调用接口不变，降低重构风险。

import logging
from fastapi import WebSocket
from room.room_manager import RoomManager
from game import ChinitsuGame
logger = logging.getLogger("uvicorn")

class GameManager:
    def __init__(self) -> None:
        self.games = dict()

    def init_game(self, room_name):
        if room_name not in self.games:
            self.games[room_name] = ChinitsuGame()
            return True
        return False  # Game already started

    def end_game(self, room_name):
        if room_name in self.games:
            del self.games[room_name]

    def get_game(self, room_name) -> ChinitsuGame:
        return self.games.get(room_name, None)


class ConnectionManager:
    """
    原有 ConnectionManager 的适配层。
    所有实际逻辑已迁移至 room/RoomManager，此类仅做接口转发。
    """

    def __init__(self, room_manager: RoomManager):
        self.room_manager = room_manager

    async def connect(
        self,
        websocket: WebSocket,
        room_name: str,
        player_id: str,
        display_name: str = "",
        vs_bot: bool = False,
        bot_level: str = "normal",
        rules: dict = None,
        debug_code: int = None,
    ) -> bool:
        """
        玩家连接入口。
        委托给 RoomManager.connect()，由其处理创建/加入/重连逻辑。
        """
        display_name = display_name or player_id
        return await self.room_manager.connect(
            websocket, room_name, player_id, display_name,
            vs_bot=vs_bot, bot_level=bot_level,
            rules=rules, debug_code=debug_code,
        )

    async def disconnect(self, websocket: WebSocket, room_name: str, player_id: str):
        """
        玩家断线入口。
        委托给 RoomManager.disconnect()。
        """
        await self.room_manager.disconnect(websocket, room_name, player_id)

    async def game_action(self, info: dict, room_name: str, player_id: str):
        """
        玩家操作入口。
        委托给 RoomManager.handle_action()。
        """
        await self.room_manager.handle_action(info, room_name, player_id)
