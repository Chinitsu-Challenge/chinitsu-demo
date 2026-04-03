# pylint: disable=missing-function-docstring, missing-module-docstring, missing-class-docstring, line-too-long, logging-fstring-interpolation
import asyncio
import logging
from typing import List, Dict
from fastapi import WebSocket
from game import ChinitsuGame
from bot_player import choose_bot_action
from replay_recorder import ReplayRecorder

logger = logging.getLogger("uvicorn")

# Stable id for the CPU seat (never a JWT uuid).
BOT_CPU_PLAYER_ID = "chinitsu-bot-cpu"


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
    def __init__(self, game_manager: GameManager):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.connection_owner : Dict[WebSocket, str] = {}
        self.connection_display_name: Dict[WebSocket, str] = {}
        self.game_manager = game_manager
        self._room_locks: Dict[str, asyncio.Lock] = {}
        self._bot_tasks: Dict[str, asyncio.Task] = {}
        self._replay_recorders: Dict[str, ReplayRecorder] = {}

    def _lock_for(self, room_name: str) -> asyncio.Lock:
        if room_name not in self._room_locks:
            self._room_locks[room_name] = asyncio.Lock()
        return self._room_locks[room_name]

    def _recorder_for(self, room_name: str) -> ReplayRecorder:
        if room_name not in self._replay_recorders:
            self._replay_recorders[room_name] = ReplayRecorder()
        return self._replay_recorders[room_name]

    async def connect(
        self,
        websocket: WebSocket,
        room_name: str,
        player_id: str,
        display_name: str = "",
        vs_bot: bool = False,
        bot_level: str = "normal",
    ):
        if room_name in self.active_connections:
            cur_game = self.game_manager.get_game(room_name)
            is_bot_room = bool(cur_game and getattr(cur_game, "vs_bot", False))
            cur_len = len(self.active_connections[room_name])
            if is_bot_room and cur_len >= 1:
                err_msg = "room_full"
                await websocket.accept()
                await websocket.close(code=1003, reason=err_msg)
                return False
            if not is_bot_room and cur_len >= 2:
                err_msg = "room_full"
                await websocket.accept()
                await websocket.close(code=1003, reason=err_msg)  # Room full
                return False
            if cur_game and player_id in cur_game.player_ids and not cur_game.is_reconnecting:
                err_msg = "duplicate_id"
                await websocket.accept()
                await websocket.close(code=1003, reason=err_msg)
                return False

        display_name = display_name or player_id
        await websocket.accept()
        if room_name not in self.active_connections:
            self.active_connections[room_name] = []
        self.active_connections[room_name].append(websocket)
        self.connection_owner[websocket] = player_id
        self.connection_display_name[websocket] = display_name

        # Initialize game for the first player (host)
        if len(self.active_connections[room_name]) == 1:
            self.game_manager.init_game(room_name)
            g = self.game_manager.get_game(room_name)
            g.add_player(player_id)
            self._recorder_for(room_name).set_display_name(player_id, display_name)
            if vs_bot:
                g.add_player(BOT_CPU_PLAYER_ID)
                self._recorder_for(room_name).set_display_name(BOT_CPU_PLAYER_ID, "CPU")
                g.vs_bot = True
                g.bot_player_id = BOT_CPU_PLAYER_ID
                g.bot_level = bot_level
                g.set_running()
                await self.broadcast(
                    f"Game started in room {room_name}! Host is {display_name}. "
                    f"Opponent: CPU ({bot_level}).",
                    room_name,
                )
            else:
                await self.broadcast(f"Game started in room {room_name}! Host is {display_name}", room_name)
        # second player (new or rejoin)
        elif len(self.active_connections[room_name]) == 2:
            cur_game = self.game_manager.get_game(room_name)
            if cur_game.is_reconnecting:
                cur_game.activate_player(player_id)
                self._recorder_for(room_name).set_display_name(player_id, display_name)
                await self.broadcast(f"{display_name} rejoins {room_name}.", room_name)
            else:
                cur_game.add_player(player_id)
                self._recorder_for(room_name).set_display_name(player_id, display_name)
                cur_game.set_running()
                logger.info(f"Game started in room {room_name}!")
                host_ws = next(ws for ws in self.active_connections[room_name] if self.connection_owner[ws] != player_id)
                host_display = self.connection_display_name[host_ws]
                await self.broadcast(f"{display_name} joins {room_name}. Host is {host_display}. Game START!", room_name)


        return True

    def disconnect(self, websocket: WebSocket, room_name: str, player_id: str):
        logger.info(f"Disconnected: {room_name} {player_id}")
        if room_name in self.active_connections:
            self.active_connections[room_name].remove(websocket)
            cur_game = self.game_manager.get_game(room_name)
            if cur_game.is_running:
                cur_game.deactivate_player(player_id)
                cur_game.set_reconnecting()
            elif cur_game.is_waiting or cur_game.is_ended:
                cur_game.remove_player(player_id)


            if len(self.active_connections[room_name]) == 0:
                t = self._bot_tasks.get(room_name)
                if t is not None and not t.done():
                    t.cancel()
                self._bot_tasks.pop(room_name, None)
                self._replay_recorders.pop(room_name, None)
                self.game_manager.end_game(room_name)
                del self.active_connections[room_name]

            self.connection_owner[websocket] = None
            self.connection_display_name.pop(websocket, None)


    async def broadcast(self, message: str, room_name: str):
        """
        Send to everyone in room_name
        """
        if room_name not in self.active_connections:
            return
        for connection in self.active_connections[room_name]:
            try:
                await connection.send_json({"broadcast":True, "message": message})
            except Exception as e:
                logger.error(f"Error in broadcast: {e}")
                self.disconnect(connection, room_name, self.connection_owner[connection])

    async def send_text_to(self, message: str, room_name: str, player_id: str):
        """
        Send text to some specific player_id in room_name
        """
        logger.info(f"{room_name} - {player_id} -> {message} ")
        if room_name not in self.active_connections:
            return
        for connection in self.active_connections[room_name]:
            if self.connection_owner[connection] == player_id:
                await connection.send_text(message)

    async def send_dict_to(self, info: dict, room_name: str, player_id: str):
        """
        Send dict to some specific player_id in room_name
        """
        info["broadcast"] = False
        logger.info(f"{room_name} - {player_id} -> {info} ")
        if room_name not in self.active_connections:
            return
        for connection in self.active_connections[room_name]:
            if self.connection_owner[connection] == player_id:
                try:
                    await connection.send_json(info)
                except Exception as e:
                    logger.error(f"Error in send_dict_to: {e}")
                    self.disconnect(connection, room_name, player_id)

    def _schedule_bot(self, room_name: str) -> None:
        existing = self._bot_tasks.get(room_name)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self._run_bot_chain(room_name))
        self._bot_tasks[room_name] = task

    async def _run_bot_chain(self, room_name: str) -> None:
        me = asyncio.current_task()
        try:
            async with self._lock_for(room_name):
                while True:
                    cur_game = self.game_manager.get_game(room_name)
                    if not cur_game or not getattr(cur_game, "vs_bot", False):
                        break
                    if cur_game.is_ended or not cur_game.is_running:
                        break
                    bot_id = cur_game.bot_player_id
                    if not bot_id:
                        break
                    choice = choose_bot_action(cur_game)
                    if choice is None:
                        break
                    result = cur_game.input(choice["action"], choice["card_idx"], bot_id)
                    if not result or bot_id not in result:
                        logger.warning("bot input returned empty: %s", choice)
                        break
                    msg = result[bot_id].get("message")
                    bot_ok = (msg == "ok") or (msg is None and choice["action"] in ("draw",))
                    if not bot_ok:
                        logger.warning("bot action rejected: %s -> %s", choice, result.get(bot_id))
                        break
                    self._record_replay_if_success(
                        room_name=room_name,
                        player_id=bot_id,
                        action=choice["action"],
                        card_idx=choice["card_idx"],
                        result=result,
                        game=cur_game,
                    )
                    for connection in self.active_connections.get(room_name, []):
                        recv_player = self.connection_owner[connection]
                        if recv_player in result:
                            await self.send_dict_to(result[recv_player], room_name, recv_player)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("bot chain failed in %s", room_name)
        finally:
            if self._bot_tasks.get(room_name) is me:
                self._bot_tasks.pop(room_name, None)

    async def game_action(self, info: dict, room_name: str, player_id: str):
        """
        Take action from clientside input
        """
        if room_name not in self.active_connections:
            return

        if info.get("action") == "export_replay":
            raw = (info.get("card_idx") or "").strip().lower()
            want_compact = raw in ("compact", "c")
            async with self._lock_for(room_name):
                rec = self._recorder_for(room_name)
                payload = rec.export_compact() if want_compact else rec.export()
            base = {"player_id": player_id, "action": "export_replay", "broadcast": False}
            if payload:
                base["replay"] = payload
                base["message"] = "ok"
            else:
                base["message"] = "no_replay_available"
            await self.send_dict_to(base, room_name, player_id)
            return

        schedule_bot = False
        async with self._lock_for(room_name):
            cur_game = self.game_manager.get_game(room_name)
            nconn = len(self.active_connections[room_name])
            if nconn < 2 and not (cur_game and getattr(cur_game, "vs_bot", False)):
                logger.info("Game not started or paused in %s", room_name)
                return
            card_idx = int(info["card_idx"]) if info["card_idx"].isdigit() else None
            result = cur_game.input(info["action"], card_idx, player_id)
            if result:
                self._record_replay_if_success(
                    room_name=room_name,
                    player_id=player_id,
                    action=info["action"],
                    card_idx=card_idx,
                    result=result,
                    game=cur_game,
                )
                for connection in self.active_connections[room_name]:
                    recv_player = self.connection_owner[connection]
                    if recv_player in result:
                        await self.send_dict_to(result[recv_player], room_name, recv_player)
                ent = result.get(player_id)
                schedule_bot = bool(ent and ent.get("message") == "ok")

        post = self.game_manager.get_game(room_name)
        if schedule_bot and post and getattr(post, "vs_bot", False):
            self._schedule_bot(room_name)

    def _record_replay_if_success(
        self,
        room_name: str,
        player_id: str,
        action: str,
        card_idx: int | None,
        result: dict,
        game: ChinitsuGame,
    ) -> None:
        recorder = self._recorder_for(room_name)
        if action in ("start", "start_new"):
            me = result.get(player_id, {})
            if me.get("message") == "ok":
                recorder.start_round(game)
            return
        me = result.get(player_id, {})
        msg = me.get("message")
        success = (msg == "ok") or (msg is None and action in ("draw",))
        if success and recorder.initial is not None:
            recorder.record_action(player_id, action, card_idx)
