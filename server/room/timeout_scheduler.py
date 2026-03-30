# room/timeout_scheduler.py — 定时器调度器
# 基于 asyncio.Task 管理所有房间级/重连级/回合级定时器。
# 支持按 key 挂载、取消、按前缀批量取消，以及幂等保护。

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger("uvicorn")


class TimeoutScheduler:
    """
    统一管理所有 asyncio 定时任务。
    每个定时器通过唯一 key 标识，到点后执行回调。
    key 约定：
      - room_expire:{room_name}             房间 40 分钟绝对寿命
      - reconnect:{room_name}:{user_id}     断线重连超时
      - skip_ron:{room_name}                AFTER_DISCARD 自动 skip_ron
      - action:{room_name}:{user_id}        行动超时（P1）
    """

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}

    async def schedule(
        self,
        key: str,
        delay_sec: float,
        callback: Callable[..., Awaitable[None]],
        *args,
    ) -> None:
        """
        注册一个定时任务。若同 key 已有任务则先取消旧任务再注册新任务。
        callback 在 delay_sec 秒后执行（除非被取消）。
        """
        await self.cancel(key)
        task = asyncio.create_task(self._run(key, delay_sec, callback, *args))
        self._tasks[key] = task
        logger.debug("Timer scheduled: %s (%.1fs)", key, delay_sec)

    async def cancel(self, key: str) -> bool:
        """
        取消指定 key 的定时任务。
        返回 True 表示确实取消了一个任务，False 表示该 key 无任务。
        """
        task = self._tasks.pop(key, None)
        if task is not None and not task.done():
            task.cancel()
            logger.debug("Timer cancelled: %s", key)
            return True
        return False

    async def cancel_prefix(self, prefix: str) -> int:
        """
        取消所有以指定前缀开头的定时任务。
        返回实际取消的数量。用于房间销毁时批量清理。
        """
        keys_to_cancel = [k for k in self._tasks if k.startswith(prefix)]
        count = 0
        for key in keys_to_cancel:
            if await self.cancel(key):
                count += 1
        return count

    def exists(self, key: str) -> bool:
        """检查指定 key 是否有活跃的定时任务"""
        task = self._tasks.get(key)
        return task is not None and not task.done()

    async def _run(
        self,
        key: str,
        delay_sec: float,
        callback: Callable[..., Awaitable[None]],
        *args,
    ):
        """内部：等待指定时间后执行回调，并清理自身引用"""
        try:
            await asyncio.sleep(delay_sec)
            logger.info("Timer fired: %s", key)
            await callback(*args)
        except asyncio.CancelledError:
            pass  # 正常取消，静默处理
        except Exception:
            logger.exception("Timer callback error for key=%s", key)
        finally:
            self._tasks.pop(key, None)

    def active_count(self) -> int:
        """返回当前活跃的定时任务数量（调试用）"""
        return sum(1 for t in self._tasks.values() if not t.done())
