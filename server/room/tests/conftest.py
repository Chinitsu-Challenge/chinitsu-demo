"""
server/room/tests/conftest.py
pytest 配置：将 server/ 加入 Python 路径，使测试可以直接 import 服务端模块。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# 文件位于 server/room/tests/conftest.py
# parent       → server/room/tests/
# parent.parent → server/room/
# parent.parent.parent → server/          ← 这是我们需要的根路径
_server_dir = Path(__file__).resolve().parent.parent.parent

_tests_dir = Path(__file__).resolve().parent

sys.path.insert(0, str(_server_dir))   # 使 room.*, game, redis_client 等可导入
sys.path.insert(0, str(_tests_dir))    # 使 helpers.py 可以直接 import

# app.py 在导入时会挂载 assets/ 目录，确保目录存在以避免导入失败
(_server_dir / "assets").mkdir(exist_ok=True)


@pytest.fixture(autouse=True)
def _no_redis():
    """
    Room 单元测试强制以无 Redis 模式运行（纯内存）。

    redis_client._client 是模块级全局单例。当两个测试套件在同一 pytest
    session 内合并运行时，集成测试初始化的 Redis 连接会泄露到 room 单元
    测试中，导致跨测试快照污染（前一个写入 Redis 的 "testroom" 快照会被
    下一个全新 RoomManager 实例在 load_snapshot() 时读到）。

    此 fixture autouse 地将所有 get_redis 调用 patch 为返回 None，
    使单元测试完全依赖 _memory_store 内存路径，与 Redis 状态完全隔离。
    """
    with patch("room.snapshot_manager.get_redis", return_value=None), \
         patch("room.room_manager.get_redis", return_value=None):
        yield
