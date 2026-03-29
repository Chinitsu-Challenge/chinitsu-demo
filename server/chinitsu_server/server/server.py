# pylint: disable=missing-function-docstring, missing-module-docstring, missing-class-docstring, line-too-long, logging-fstring-interpolation
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Dict
from game import ChinitsuGame
from database import init_db
from auth import verify_token, register_user, authenticate_user
from models import RegisterRequest, LoginRequest, TokenResponse


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)
logger = logging.getLogger("uvicorn")

_ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/register", response_model=TokenResponse)
async def api_register(req: RegisterRequest):
    try:
        result = await register_user(req.username, req.password)
        return TokenResponse(
            access_token=result["access_token"],
            uuid=result["uuid"],
            username=result["username"],
        )
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"detail": str(e)})


@app.post("/api/login", response_model=TokenResponse)
async def api_login(req: LoginRequest):
    try:
        result = await authenticate_user(req.username, req.password)
        return TokenResponse(
            access_token=result["access_token"],
            uuid=result["uuid"],
            username=result["username"],
        )
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"detail": str(e)})

# Static file paths
_SERVER_DIR = Path(__file__).resolve().parent
_CHINITSU_DIR = _SERVER_DIR.parent            # chinitsu_server
_PROJECT_DIR = _CHINITSU_DIR.parent.parent    # project root (chinitsu)

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

    async def connect(self, websocket: WebSocket, room_name: str, player_id: str, display_name: str = ""):
        if room_name in self.active_connections:
            if len(self.active_connections[room_name]) >= 2:
                err_msg = "room_full"
                await websocket.accept()
                await websocket.close(code=1003, reason=err_msg)  # Room full
                return False
            cur_game = self.game_manager.get_game(room_name)
            if player_id in cur_game.player_ids and not cur_game.is_reconnecting:  # same id but not reconnecting, so duplicate id.
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
            self.game_manager.get_game(room_name).add_player(player_id)
            await self.broadcast(f"Game started in room {room_name}! Host is {display_name}", room_name)
        # second player (new or rejoin)
        elif len(self.active_connections[room_name]) == 2:
            cur_game = self.game_manager.get_game(room_name)
            if cur_game.is_reconnecting:
                cur_game.activate_player(player_id)
                await self.broadcast(f"{display_name} rejoins {room_name}.", room_name)
            else:
                cur_game.add_player(player_id)
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

    async def game_action(self, info: dict, room_name: str, player_id: str):
        """
        Take action from clientside input
        """
        if room_name not in self.active_connections:
            return
        cur_game = self.game_manager.get_game(room_name)
        # make the action if both players are connected
        if len(self.active_connections[room_name]) < 2:
            logger.info("Game not started or paused in %s", room_name)
            return
        card_idx = int(info["card_idx"]) if info["card_idx"].isdigit() else None
        result = cur_game.input(info["action"], card_idx, player_id)
        if result:
            for connection in self.active_connections[room_name]:
                recv_player = self.connection_owner[connection]
                if recv_player in result:
                    await self.send_dict_to(result[recv_player], room_name, recv_player)


gm = GameManager()
manager = ConnectionManager(gm)

# Mount static files (assets and web frontend)
app.mount("/assets", StaticFiles(directory=_CHINITSU_DIR / "assets"), name="assets")


@app.websocket("/ws/{room_name}")
async def websocket_endpoint(websocket: WebSocket, room_name: str, token: str = Query("")):
    # Validate JWT token
    payload = verify_token(token)
    if payload is None:
        await websocket.accept()
        await websocket.close(code=1008, reason="invalid_token")
        return

    player_id = payload["uuid"]
    display_name = payload["username"]

    if not await manager.connect(websocket, room_name, player_id, display_name):
        return

    try:
        while True:
            data = await websocket.receive_json()
            await manager.game_action(data, room_name, player_id)
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_name, player_id)
        await manager.broadcast(f"{display_name} left the room {room_name}", room_name)


# API docs (AsyncAPI spec + viewer) — must come before the root mount
@app.get("/api-docs")
async def redirect_api_docs():
    return RedirectResponse(url="/api-docs/")

app.mount("/api-docs", StaticFiles(directory=_PROJECT_DIR / "docs", html=True), name="api-docs")

# Web frontend (must be last — catches all remaining paths)
# Prefer Svelte build output; fall back to legacy web/ directory
_WEB_DIR = _PROJECT_DIR / "web-svelte" / "build"
if not _WEB_DIR.is_dir():
    _WEB_DIR = _PROJECT_DIR / "web"
app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
