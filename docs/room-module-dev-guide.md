# Room 模块增量开发指南

## 核心原则

每个新功能通常只需改动以下 4 个地方：

1. [models.py](../server/room/models.py) — 数据结构
2. [room_manager.py](../server/room/room_manager.py) — 业务逻辑
3. [protocol.py](../server/room/protocol.py) — 消息格式
4. `docs/asyncapi.yaml` + `docs/asyncapi.zh.yaml` — 协议文档

---

## 示例：添加"自定义轮数上限"规则

### 第一步：在 models.py 中扩展数据模型

`Room` 已有 `round_limit` 字段，新规则按同样模式加入：

```python
# models.py — 常量区
CUSTOM_TIME_LIMIT_SEC = 60   # 新增

# Room dataclass
@dataclass
class Room:
    round_limit: int = DEFAULT_ROUND_LIMIT
    time_limit: int = CUSTOM_TIME_LIMIT_SEC   # 新增字段
```

必须同步更新 `to_redis_dict()` 和 `from_redis_dict()`，否则重启/重连后数据丢失：

```python
def to_redis_dict(self) -> dict:
    return {
        ...
        "time_limit": str(self.time_limit),
    }

@classmethod
def from_redis_dict(cls, data: dict) -> "Room":
    return cls(
        ...
        time_limit=int(data.get("time_limit", CUSTOM_TIME_LIMIT_SEC)),
    )
```

### 第二步：在 room_manager.py 中接收客户端传入的规则值

规则值一般随 `start` action 传入。在 `_create_room()` 里读取（如果需要更多字段，从 `handle_action` 往下透传）：

```python
# _create_room() 中（第一个人创建房间时写入规则）
room = Room(
    ...
    round_limit=data.get("round_limit", DEFAULT_ROUND_LIMIT),
)
```

游戏层规则（赔点数、大车轮等）通过 `ChinitsuGame` 的 `set_rules()` 传入，见 [game.py](../server/game.py) 中的 `default_rules` 字典：

```python
# room_manager.py — _handle_start() 里创建游戏时
game = ChinitsuGame(rules={"initial_point": room.initial_point})
```

### 第三步：添加新的客户端 Action（可选）

如果新功能需要新 action（如 `set_rules`），在 `handle_action()` 的状态分发块中加一行：

```python
if room.status == RoomStatus.WAITING:
    if action == "set_rules":
        await self._handle_set_rules(room, user_id, data)  # 新增分支
    elif action in ("start", ...):
        ...
```

然后实现对应的私有方法 `_handle_set_rules()`。

### 第四步：添加新的服务端事件（可选）

如果需要通知客户端规则变更，在 [protocol.py](../server/room/protocol.py) 中添加工厂函数：

```python
def make_rules_changed(round_limit: int) -> dict:
    return {
        "broadcast": True,
        "event": "rules_changed",
        "round_limit": round_limit,
    }
```

广播用 `self.push.broadcast(room_name, protocol.make_rules_changed(...))`，单播用 `self.push.unicast(...)`。

### 第五步：更新前端处理

在 [ws.ts](../web-svelte/src/lib/ws.ts) 的 `handleBroadcastEvent()` 里加对应 case：

```typescript
case "rules_changed":
    gameState.update(s => ({ ...s, roundLimit: data.round_limit }));
    break;
```

### 第六步：同步 AsyncAPI 文档

修改以下位置（`asyncapi.yaml` 和 `asyncapi.zh.yaml` 两个文件都要改）：

- 新 action → `components/schemas/ActionType/enum`
- 新事件 → `components/messages/` + channel `subscribe.oneOf`
- 新字段 → `components/schemas/` 对应 payload schema

---

## 关键文件速查

| 要改什么 | 改哪里 |
|---|---|
| 房间配置字段 | [models.py](../server/room/models.py) — `Room` dataclass + `to/from_redis_dict` |
| 游戏规则（赔点、yaku） | [game.py](../server/game.py) — `default_rules` → 传入 `ChinitsuGame(rules=...)` |
| 新 action 路由 | [room_manager.py](../server/room/room_manager.py) — `handle_action()` |
| 新服务端消息格式 | [protocol.py](../server/room/protocol.py) — 添加 `make_xxx()` 函数 |
| 错误码 | [errors.py](../server/room/errors.py) |
| 定时器（超时逻辑） | [timeout_scheduler.py](../server/room/timeout_scheduler.py) |
| 前端消息处理 | [ws.ts](../web-svelte/src/lib/ws.ts) — `handleBroadcastEvent()` |

---

## 注意事项

- **Redis 序列化**：`Room` 和 `PlayerSession` 的所有新字段都要加进 `to_redis_dict()` / `from_redis_dict()`，漏掉会导致服务重启或玩家重连后字段丢失/报错。
- **状态机约束**：在 `handle_action()` 里操作前先检查 `room.status`，不要在 RECONNECT 状态下处理游戏逻辑。
- **测试**：参考 [server/room/tests/](../server/room/tests/) 下的现有测试，用 `helpers.py` 里的 `make_room()` / `make_session()` 构造测试数据，`run_async()` 执行协程。
