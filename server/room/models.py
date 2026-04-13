# room/models.py — 房间模块核心数据模型
# 定义 Room、PlayerSession 数据类，以及 RoomStatus、RoomEvent 枚举

from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket


# ── 房间状态枚举 ────────────────────────────────────────────────
class RoomStatus(str, Enum):
    WAITING   = "waiting"      # 等待玩家加入 / 等待双方确认开始
    RUNNING   = "running"      # 对局进行中（包含多轮，单轮结束后仍为 RUNNING）
    RECONNECT = "reconnect"    # 一方断线，等待重连
    ENDED     = "ended"        # 整个比赛结束（轮数到上限 / 有人 point<0）
    DESTROYED = "destroyed"    # 终态标记，仅逻辑使用


# ── 房间事件枚举 ────────────────────────────────────────────────
class RoomEvent(str, Enum):
    CREATE             = "create"              # [空] → WAITING
    BOTH_READY         = "both_ready"          # WAITING → RUNNING
    PLAYER_DISCONNECT  = "player_disconnect"   # RUNNING → RECONNECT
    PLAYER_RECONNECT   = "player_reconnect"    # RECONNECT → RUNNING
    MATCH_END          = "match_end"           # RUNNING → ENDED
    RECONNECT_TIMEOUT  = "reconnect_timeout"   # RECONNECT → ENDED
    BOTH_CONTINUE      = "both_continue"       # ENDED → WAITING
    ANY_END_GAME       = "any_end_game"        # ENDED → DESTROYED
    ROOM_EXPIRED       = "room_expired"        # 任意 → DESTROYED
    ALL_LEFT           = "all_left"            # 任意 → DESTROYED
    BOTH_OFFLINE       = "both_offline"        # RECONNECT → DESTROYED


# ── 默认配置 ────────────────────────────────────────────────────
ROOM_MAX_LIFETIME_SEC = 40 * 60      # 房间绝对寿命：40 分钟
RECONNECT_TIMEOUT_SEC = 120          # 断线重连超时：120 秒
SKIP_RON_TIMEOUT_SEC = 30            # AFTER_DISCARD 等待超时：30 秒
DEFAULT_ROUND_LIMIT = 8              # 默认比赛轮数上限


# ── 玩家会话 ────────────────────────────────────────────────────
@dataclass
class PlayerSession:
    """
    房间内的玩家会话对象。
    将 WebSocket 连接与玩家身份绑定，管理在线/离线状态。
    """
    user_id: str                            # 用户唯一标识（UUID，来自 JWT）
    display_name: str                       # 昵称（仅展示用）
    room_name: str                          # 所属房间名
    seat: int                               # 座位号：0 或 1
    is_owner: bool                          # 是否房主（先连接者）
    online: bool = True                     # 是否在线
    last_seen: float | None = None          # 断线时间戳，在线时为 None
    ws: "WebSocket | None" = None           # 当前 WebSocket 连接（仅内存，不序列化）
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # connection_id：每次建立连接时生成，用于区分新旧连接，防止旧 disconnect 事件误伤新连接

    def mark_offline(self):
        """标记玩家离线"""
        self.online = False
        self.last_seen = time.time()
        self.ws = None

    def mark_online(self, ws: "WebSocket", connection_id: str | None = None):
        """标记玩家上线（含重连场景）"""
        self.online = True
        self.last_seen = None
        self.ws = ws
        self.connection_id = connection_id or str(uuid.uuid4())

    def to_redis_dict(self) -> dict:
        """序列化为可存入 Redis 的字典（排除不可序列化的 ws）"""
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "room_name": self.room_name,
            "seat": str(self.seat),
            "is_owner": str(self.is_owner).lower(),
            "online": str(self.online).lower(),
            "last_seen": str(self.last_seen or 0),
            "connection_id": self.connection_id,
        }


# ── 旁观者会话 ──────────────────────────────────────────────────
@dataclass
class SpectatorSession:
    """
    旁观者会话对象。
    与 PlayerSession 的关键区别：
    - 不持久化到 Redis（断线即离开，无会话恢复）
    - 无在线/离线状态区分（ws 为 None 即已离开）
    - 无 connection_id（无需防旧连接误触发）
    - 不参与状态机、投票、断线重连逻辑
    """
    user_id: str                            # 用户唯一标识（来自 JWT）
    display_name: str                       # 昵称
    room_name: str                          # 所在房间名
    ws: "WebSocket | None" = None           # 当前 WebSocket 连接
    joined_at: float = field(default_factory=time.time)


# ── 旁观者数量上限 ───────────────────────────────────────────────
MAX_SPECTATORS_PER_ROOM = 10


# ── 房间对象 ────────────────────────────────────────────────────
@dataclass
class Room:
    """
    房间完整状态。
    包含生命周期状态、玩家列表、投票状态、比赛进度等。
    """
    room_id: str                                # 房间实例唯一 ID（防止 timer 误杀新房间）
    room_name: str                              # 房间名（由客户端指定）
    status: RoomStatus = RoomStatus.WAITING     # 当前房间状态
    owner_id: str = ""                          # 房主 user_id
    player_ids: list[str] = field(default_factory=list)   # 按入座顺序
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float = 0.0                     # created_at + ROOM_MAX_LIFETIME_SEC
    game_id: str | None = None                  # 当前绑定的游戏标识（= room_name）
    reconnect_deadline: float | None = None     # 重连截止时间戳
    ready_user_ids: set[str] = field(default_factory=set)      # WAITING 中已 start 的玩家
    continue_user_ids: set[str] = field(default_factory=set)   # ENDED 中已 continue 的玩家
    round_no: int = 0                           # 当前已完成的轮数
    round_limit: int = DEFAULT_ROUND_LIMIT      # 比赛轮数上限

    def __post_init__(self):
        if self.expires_at == 0.0:
            self.expires_at = self.created_at + ROOM_MAX_LIFETIME_SEC

    def touch(self):
        """更新最后修改时间"""
        self.updated_at = time.time()

    @property
    def is_full(self) -> bool:
        return len(self.player_ids) >= 2

    @property
    def online_user_ids(self) -> list[str]:
        """需要外部传入 sessions 才能判断，这里只提供 player_ids"""
        return list(self.player_ids)

    def to_redis_dict(self) -> dict:
        """序列化为可存入 Redis 的字典"""
        import json
        return {
            "room_id": self.room_id,
            "room_name": self.room_name,
            "status": self.status.value,
            "owner_id": self.owner_id,
            "player_ids": json.dumps(self.player_ids),
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
            "expires_at": str(self.expires_at),
            "game_id": self.game_id or "",
            "reconnect_deadline": str(self.reconnect_deadline or ""),
            "ready_user_ids": json.dumps(list(self.ready_user_ids)),
            "continue_user_ids": json.dumps(list(self.continue_user_ids)),
            "round_no": str(self.round_no),
            "round_limit": str(self.round_limit),
        }

    @classmethod
    def from_redis_dict(cls, data: dict) -> "Room":
        """从 Redis Hash 反序列化"""
        import json
        reconnect_deadline = data.get("reconnect_deadline", "")
        return cls(
            room_id=data["room_id"],
            room_name=data["room_name"],
            status=RoomStatus(data["status"]),
            owner_id=data["owner_id"],
            player_ids=json.loads(data.get("player_ids", "[]")),
            created_at=float(data.get("created_at", 0)),
            updated_at=float(data.get("updated_at", 0)),
            expires_at=float(data.get("expires_at", 0)),
            game_id=data.get("game_id") or None,
            reconnect_deadline=float(reconnect_deadline) if reconnect_deadline else None,
            ready_user_ids=set(json.loads(data.get("ready_user_ids", "[]"))),
            continue_user_ids=set(json.loads(data.get("continue_user_ids", "[]"))),
            round_no=int(data.get("round_no", 0)),
            round_limit=int(data.get("round_limit", DEFAULT_ROUND_LIMIT)),
        )
