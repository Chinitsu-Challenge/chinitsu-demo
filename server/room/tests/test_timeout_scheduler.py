"""
tests/room/test_timeout_scheduler.py
TimeoutScheduler 单元测试：定时器挂载、取消、前缀批量取消。
"""
import asyncio
import pytest
from tests.room.conftest import run_async

from room.timeout_scheduler import TimeoutScheduler


def test_schedule_and_fire():
    """到点后回调应被执行"""
    fired = []

    async def callback(val):
        fired.append(val)

    async def inner():
        sched = TimeoutScheduler()
        await sched.schedule("key1", 0.01, callback, 42)
        await asyncio.sleep(0.05)
        assert fired == [42]

    run_async(inner())


def test_cancel_before_fire():
    """取消后回调不应执行"""
    fired = []

    async def callback():
        fired.append(True)

    async def inner():
        sched = TimeoutScheduler()
        await sched.schedule("key1", 0.1, callback)
        cancelled = await sched.cancel("key1")
        assert cancelled is True
        await asyncio.sleep(0.2)
        assert fired == []

    run_async(inner())


def test_cancel_nonexistent_key():
    """取消不存在的 key 应返回 False 且不报错"""
    async def inner():
        sched = TimeoutScheduler()
        result = await sched.cancel("nonexistent")
        assert result is False

    run_async(inner())


def test_cancel_already_fired():
    """取消已触发的 timer 返回 False"""
    async def inner():
        sched = TimeoutScheduler()
        await sched.schedule("k", 0.01, lambda: None)
        await asyncio.sleep(0.05)
        result = await sched.cancel("k")
        assert result is False  # 已经执行完毕，任务不再存在

    run_async(inner())


def test_reschedule_replaces_old_timer():
    """同一 key 重新 schedule 应取消旧计时器并挂载新的"""
    calls = []

    async def callback(label):
        calls.append(label)

    async def inner():
        sched = TimeoutScheduler()
        await sched.schedule("k", 0.1, callback, "old")
        await asyncio.sleep(0.02)
        await sched.schedule("k", 0.01, callback, "new")  # 替换旧的
        await asyncio.sleep(0.05)
        # 旧 callback 不应触发，新 callback 触发一次
        assert calls == ["new"], f"Expected ['new'], got {calls}"

    run_async(inner())


def test_cancel_prefix():
    """按前缀批量取消定时器"""
    fired = []

    async def callback(label):
        fired.append(label)

    async def inner():
        sched = TimeoutScheduler()
        await sched.schedule("reconnect:room1:alice", 0.2, callback, "alice")
        await sched.schedule("reconnect:room1:bob", 0.2, callback, "bob")
        await sched.schedule("room_expire:room1", 0.2, callback, "expire")

        count = await sched.cancel_prefix("reconnect:room1")
        assert count == 2

        await asyncio.sleep(0.3)
        # 只有 room_expire 应触发
        assert fired == ["expire"]

    run_async(inner())


def test_exists_true():
    """exists 对活跃 timer 返回 True"""
    async def inner():
        sched = TimeoutScheduler()
        await sched.schedule("k", 1.0, lambda: None)
        assert sched.exists("k") is True
        await sched.cancel("k")

    run_async(inner())


def test_exists_false():
    """exists 对不存在的 key 返回 False"""
    async def inner():
        sched = TimeoutScheduler()
        assert sched.exists("nonexistent") is False

    run_async(inner())


def test_active_count():
    """active_count 应正确统计活跃定时器数量"""
    async def inner():
        sched = TimeoutScheduler()
        await sched.schedule("a", 1.0, lambda: None)
        await sched.schedule("b", 1.0, lambda: None)
        assert sched.active_count() == 2
        await sched.cancel("a")
        assert sched.active_count() == 1
        await sched.cancel("b")
        assert sched.active_count() == 0

    run_async(inner())


def test_callback_exception_does_not_crash_scheduler():
    """回调函数抛异常不应影响调度器本身"""
    async def bad_callback():
        raise ValueError("intentional error")

    async def inner():
        sched = TimeoutScheduler()
        await sched.schedule("k", 0.01, bad_callback)
        await asyncio.sleep(0.05)  # 等待触发
        # 调度器仍应正常工作
        assert sched.active_count() == 0  # key 应被清理

    run_async(inner())
