# redis_client.py — Redis 异步客户端单例
# 提供全局 Redis 连接，供房间模块各服务使用

import os
import logging
import redis.asyncio as aioredis

logger = logging.getLogger("uvicorn")

_client: aioredis.Redis | None = None


async def init_redis(url: str | None = None) -> aioredis.Redis:
    """
    初始化 Redis 连接。在 FastAPI lifespan 启动时调用。
    默认连接 localhost:6379，可通过 REDIS_URL 环境变量覆盖。
    """
    global _client
    url = url or os.environ.get("REDIS_URL", "redis://8.155.149.12:26379/0")
    _client = aioredis.from_url(url, decode_responses=True)
    # 测试连接是否可用
    try:
        await _client.ping()
        logger.info("Redis 连接成功: %s", url)
    except Exception as e:
        logger.warning("Redis 连接失败 (%s)，将以无持久化模式运行: %s", url, e)
        _client = None
    return _client


def get_redis() -> aioredis.Redis | None:
    """获取 Redis 客户端实例。若未初始化或连接失败则返回 None。"""
    return _client


async def close_redis():
    """关闭 Redis 连接。在 FastAPI lifespan 关闭时调用。"""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except RuntimeError as e:
            # 测试环境中 room 单元测试会在独立 event loop 中使用 Redis 连接，
            # 这些临时 loop 关闭后连接池中会有 orphaned 连接。
            # 关闭时忽略 "Event loop is closed" 错误，不影响正确性。
            logger.debug("Redis 关闭时忽略 event loop 错误: %s", e)
        except Exception as e:
            logger.warning("Redis 关闭时出错: %s", e)
        _client = None
        logger.info("Redis 连接已关闭")
