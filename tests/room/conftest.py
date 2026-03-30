"""
tests/room/conftest.py
房间模块测试共享夹具与工具类
"""
import sys
import asyncio
from pathlib import Path

# 将 server/ 加入 Python 路径，使测试可以直接 import 服务端模块
_server_dir = Path(__file__).resolve().parent.parent.parent / "server"
sys.path.insert(0, str(_server_dir))

# 确保 assets 目录存在（app.py 在导入时会挂载此目录）
(_server_dir / "assets").mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════
# MockWebSocket：模拟 FastAPI WebSocket 对象
# ══════════════════════════════════════════════════════════════

class MockWebSocket:
    """
    模拟 WebSocket 连接对象。
    记录所有 send_json 发送的消息、关闭状态等，供测试断言。
    """

    def __init__(self, user_id: str = "mock-user"):
        self.user_id = user_id
        self.sent: list[dict] = []         # 所有已发送消息
        self.closed: bool = False
        self.close_code: int | None = None
        self.close_reason: str = ""
        self.accepted: bool = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, data: dict):
        if self.closed:
            raise RuntimeError(f"WebSocket [{self.user_id}] is closed, cannot send")
        self.sent.append(dict(data))

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    async def receive_json(self):
        raise NotImplementedError("receive_json is not used in unit tests")

    # ── 辅助查询方法 ───────────────────────────────────────────

    def last(self) -> dict | None:
        """最后一条收到的消息"""
        return self.sent[-1] if self.sent else None

    def events(self, event_type: str) -> list[dict]:
        """过滤指定 event 类型的消息"""
        return [m for m in self.sent if m.get("event") == event_type]

    def last_event(self, event_type: str) -> dict | None:
        """最后一条指定类型事件"""
        evts = self.events(event_type)
        return evts[-1] if evts else None

    def clear(self):
        self.sent.clear()


# ══════════════════════════════════════════════════════════════
# 异步测试辅助：将 async 测试包装为同步
# ══════════════════════════════════════════════════════════════

def run_async(coro):
    """在同步测试中运行协程（避免依赖 pytest-asyncio 版本问题）"""
    return asyncio.get_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════
# 快速搭建含两名玩家的 RoomManager
# ══════════════════════════════════════════════════════════════

async def setup_two_player_room(room_name="testroom") -> tuple:
    """
    创建房间管理器，连接两名玩家，返回 (room_manager, ws_alice, ws_bob)。
    两名玩家都已连接，房间处于 WAITING 状态。
    """
    from room.room_manager import RoomManager
    rm = RoomManager()

    ws_alice = MockWebSocket("alice")
    ws_bob = MockWebSocket("bob")

    await rm.connect(ws_alice, room_name, "uid-alice", "Alice")
    await rm.connect(ws_bob, room_name, "uid-bob", "Bob")

    return rm, ws_alice, ws_bob


async def setup_running_room(room_name="testroom", debug_code=None) -> tuple:
    """
    创建房间管理器，连接两名玩家并让双方 start，返回 RUNNING 状态的房间。
    返回 (room_manager, ws_alice, ws_bob)
    """
    rm, ws_alice, ws_bob = await setup_two_player_room(room_name)

    card_idx = str(debug_code) if debug_code else ""
    await rm.handle_action({"action": "start", "card_idx": card_idx}, room_name, "uid-alice")
    await rm.handle_action({"action": "start", "card_idx": card_idx}, room_name, "uid-bob")

    return rm, ws_alice, ws_bob
