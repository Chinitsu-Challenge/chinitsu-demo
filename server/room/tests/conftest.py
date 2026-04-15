"""
server/room/tests/conftest.py
pytest 配置：将 server/ 加入 Python 路径，使测试可以直接 import 服务端模块。
"""
import asyncio
import logging
import os
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

_logger = logging.getLogger("pytest")


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


@pytest.fixture(scope="session", autouse=True)
def _cleanup_redis_after_session():
    """
    整个 pytest session 结束后清理 Redis 中的测试残留数据。

    问题根因：
    集成测试（tests/test_server.py）通过真实 FastAPI lifespan 连接 Redis，
    在运行过程中会写入 room / player_session / snapshot 键以及 room_index。
    lifespan 关闭时仅断开连接，不删除已写入的键，因此测试结束后这些数据
    会一直留在 Redis 中，污染开发环境并干扰后续测试。

    修复方案：
    在所有测试（包括集成测试和本套单元测试）全部结束后，用独立连接扫描并
    删除所有游戏相关键（room:* / player_session:* / snapshot:* / room_index）。
    使用独立连接而非 redis_client.get_redis()，确保即使连接已关闭也能完成
    清理。
    """
    yield  # 先跑完所有测试

    import redis.asyncio as aioredis  # 局部 import，避免影响模块加载顺序

    async def _flush_test_keys() -> None:
        url = os.environ.get("REDIS_URL", "redis://8.155.149.12:26379/0")
        client: aioredis.Redis = aioredis.from_url(url, decode_responses=True)
        try:
            await client.ping()
        except Exception:
            return  # Redis 不可用（如 CI 环境无 Redis），跳过清理

        deleted = 0
        try:
            keys: list[str] = []
            for pattern in ("room:*", "player_session:*", "snapshot:*"):
                async for key in client.scan_iter(pattern):
                    keys.append(key)
            if keys:
                deleted += await client.delete(*keys)
            # room_index 是集合，单独删除
            deleted += await client.delete("room_index")
        except Exception as exc:
            _logger.warning("Redis 测试数据清理失败: %s", exc)
        else:
            if deleted:
                _logger.info("已清理 %d 个 Redis 测试键", deleted)
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_flush_test_keys())
    except Exception as exc:
        _logger.warning("Redis 清理 event loop 执行失败: %s", exc)
    finally:
        loop.close()
