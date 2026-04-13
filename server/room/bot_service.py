# room/bot_service.py — Bot 调度服务
# 职责：接管 vs-bot 房间中 CPU 行动的异步调度。
# 与 RoomManager 通过引用协作，但不修改 game.py 或任何游戏层代码。

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from bot_player import choose_bot_action, BOT_ID

if TYPE_CHECKING:
    from room.room_manager import RoomManager

logger = logging.getLogger("uvicorn")


class BotService:
    """
    Bot 行动调度器。
    每个 vs-bot 房间维护一个 asyncio.Task 链：
      人类行动结束 → schedule() → _run_chain() 连续处理 bot 的所有后续行动
      直到轮到人类行动、或游戏结束为止。
    """

    def __init__(self, room_manager: "RoomManager"):
        self._rm = room_manager
        # room_name → 当前运行中的 Task
        self._tasks: dict[str, asyncio.Task] = {}

    # ── 公开接口 ──────────────────────────────────────────────────

    def schedule(self, room_name: str) -> None:
        """
        在人类行动后调用，触发 bot 的连续行动链。
        若已有任务在运行则忽略（避免重复调度）。
        """
        existing = self._tasks.get(room_name)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self._run_chain(room_name))
        self._tasks[room_name] = task

    def cleanup_room(self, room_name: str) -> None:
        """房间销毁时取消未完成的 bot 任务"""
        task = self._tasks.pop(room_name, None)
        if task and not task.done():
            task.cancel()

    # ── 内部实现 ──────────────────────────────────────────────────

    async def _run_chain(self, room_name: str) -> None:
        """
        Bot 行动链：持续调用 choose_bot_action() 并执行，
        直到 bot 无需再行动（轮到人类）或游戏结束。
        """
        me = asyncio.current_task()
        try:
            while True:
                rm = self._rm
                room = rm.rooms.get(room_name)
                game = rm.games.get(room_name)

                if room is None or game is None or not room.vs_bot:
                    break
                if game.is_ended or not game.is_running:
                    break

                choice = choose_bot_action(game, BOT_ID, room.bot_level)
                if choice is None:
                    break  # 轮到人类行动

                # 执行 bot 操作
                try:
                    result = game.input(choice["action"], choice["card_idx"], BOT_ID)
                except Exception:
                    logger.exception("bot game.input 异常 [%s] choice=%s", room_name, choice)
                    break

                if not result or BOT_ID not in result:
                    logger.warning("bot input 返回空 [%s] choice=%s", room_name, choice)
                    break

                # 校验 bot 操作是否被接受
                bot_msg = result[BOT_ID].get("message")
                action_ok = bot_msg == "ok" or (
                    bot_msg is None and choice["action"] == "draw"
                )
                if not action_ok:
                    logger.warning(
                        "bot 操作被拒绝 [%s] %s -> %s", room_name, choice, bot_msg
                    )
                    break

                # 将结果推送给真实玩家（bot 的 unicast 会静默忽略）
                wall_count = len(game.yama)
                for target_id, info in result.items():
                    info["broadcast"] = False
                    info["wall_count"] = wall_count
                    await rm.push.unicast(room_name, target_id, info)

                # 快照保存 + 比赛结束判断
                await rm._post_action_bookkeeping(room, game)

                if game.is_ended:
                    break

                # 让出事件循环，避免长时间占用
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("bot chain 崩溃 [%s]", room_name)
        finally:
            if self._tasks.get(room_name) is me:
                self._tasks.pop(room_name, None)
