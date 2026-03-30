# pylint: disable=missing-function-docstring, missing-module-docstring, missing-class-docstring, line-too-long, logging-fstring-interpolation
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from database import init_db
from redis_client import init_redis, close_redis
from auth import verify_token, register_user, authenticate_user
from models import RegisterRequest, LoginRequest, TokenResponse
from room.room_manager import RoomManager
from managers import ConnectionManager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 启动时初始化数据库和 Redis
    await init_db()
    await init_redis()
    yield
    # 关闭时清理 Redis 连接
    await close_redis()


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
        return JSONResponse(status_code=401, content={"detail": str(e)})


# Path configuration
_SERVER_DIR = Path(__file__).resolve().parent        # server/
_PROJECT_DIR = _SERVER_DIR.parent                    # project root

# 全局实例：RoomManager 是新的核心管理器
room_manager = RoomManager()
manager = ConnectionManager(room_manager)

# Mount static files (tile assets)
app.mount("/assets", StaticFiles(directory=_SERVER_DIR / "assets"), name="assets")


@app.websocket("/ws/{room_name}")
async def websocket_endpoint(websocket: WebSocket, room_name: str, token: str = Query("")):
    # 验证 JWT token
    payload = verify_token(token)
    if payload is None:
        await websocket.accept()
        await websocket.close(code=1008, reason="invalid_token")
        return

    player_id = payload["uuid"]
    display_name = payload["username"]

    # 连接到房间（RoomManager 处理创建/加入/重连）
    if not await manager.connect(websocket, room_name, player_id, display_name):
        return

    try:
        while True:
            data = await websocket.receive_json()
            await manager.game_action(data, room_name, player_id)
    except WebSocketDisconnect:
        # 断线处理（RoomManager 根据状态决定移除/重连/销毁）
        await manager.disconnect(websocket, room_name, player_id)


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
