# Room 模块增量开发指南

> 规则只在创建房间时设置，对局中不可修改。

---

## 目录

1. [规则分类](#1-规则分类)
2. [推荐架构：统一 RoomConfig](#2-推荐架构统一-roomconfig)
3. [详细示例：添加回合时间上限](#3-详细示例添加回合时间上限)
4. [对局规则（game.py 侧）](#4-对局规则gamepy-侧)
5. [关键文件速查](#5-关键文件速查)
6. [规范与注意事项](#6-规范与注意事项)

---

## 1. 规则分类

在动手之前，先判断你的规则属于哪一层：

| 类型 | 含义 | 归属 | 典型例子 |
|---|---|---|---|
| **回合规则** | 与房间状态机、回合切换、等待超时相关 | `room/` 模块 | 每轮时间上限、断线等待时长、最大轮数 |
| **对局规则** | 与牌局计算、役种判定、点数逻辑相关 | `game.py` | 初始点数、有无大车轮、人和是否算役满 |

回合规则你全权负责；对局规则只需把参数传进 `ChinitsuGame(rules={...})`，游戏层自己处理（见[第 4 节](#4-对局规则gamepy-侧)）。

---

## 2. 推荐架构：统一 RoomConfig

### 为什么不要一个规则加一个字段

如果每条规则都直接挂在 `Room` dataclass 上，随着规则增多：
- `Room` 字段膨胀，Redis 序列化/反序列化每次都要改两处
- `_create_room()` 的参数列表越来越长
- 前端传参没有统一入口

### 推荐做法：在 Room 里增加一个 `config` 字典

```python
# room/models.py

# ── 默认配置 ────────────────────────────────────────────────────
DEFAULT_ROOM_CONFIG = {
    "round_limit": 8,           # 最大轮数
    "turn_time_limit": 0,       # 每回合时间上限（秒），0 = 不限时
    # 未来新规则直接加这里 ↓
}

@dataclass
class Room:
    ...
    config: dict = field(default_factory=lambda: dict(DEFAULT_ROOM_CONFIG))
```

Redis 序列化只需改一处：

```python
def to_redis_dict(self) -> dict:
    import json
    return {
        ...
        "config": json.dumps(self.config),
    }

@classmethod
def from_redis_dict(cls, data: dict) -> "Room":
    import json
    return cls(
        ...
        config=json.loads(data.get("config", "{}")),
    )
```

客户端在建立 WebSocket 连接时，通过 query 参数传入自定义规则（`room_manager.py` 的 `connect()` 里解析）：

```
ws://.../ws/{room_name}?token=xxx&round_limit=4&turn_time_limit=30
```

或者通过 `start` action 的 payload 传入（推荐，因为可以在大厅 UI 里设置）：

```json
{ "action": "start", "config": { "round_limit": 4, "turn_time_limit": 30 } }
```

> **约定**：`config` 只在房间创建时（`_create_room()`）写入，之后只读。`_handle_start()` 等地方通过 `room.config.get(...)` 读取。

---

## 3. 详细示例：添加回合时间上限

> 需求：每名玩家的出牌回合有时间限制，超时后自动 skip（或随机打牌）。

### Step 1 — models.py：声明规则常量

```python
# room/models.py

DEFAULT_ROOM_CONFIG = {
    "round_limit": 8,
    "turn_time_limit": 0,   # ← 新增，0 = 不限时
}
```

如果你还没有统一 `config` 字段，也可以先单独加：

```python
@dataclass
class Room:
    ...
    turn_time_limit: int = 0   # 每回合秒数，0 = 不限时
```

必须同步 `to_redis_dict()` 和 `from_redis_dict()`：

```python
# to_redis_dict
"turn_time_limit": str(self.turn_time_limit),

# from_redis_dict
turn_time_limit=int(data.get("turn_time_limit", 0)),
```

### Step 2 — room_manager.py：创建房间时读取规则

在 `_create_room()` 里从客户端请求里读取规则，写入 Room（**只写一次**）：

```python
# room/room_manager.py — _create_room()

async def _create_room(
    self, ws: WebSocket, room_name: str, user_id: str, display_name: str,
    options: dict | None = None,   # ← 新增 options 参数，由 connect() 传入
) -> None:
    options = options or {}
    room = Room(
        ...
        turn_time_limit=int(options.get("turn_time_limit", 0)),
    )
```

在 `connect()` 里，从 WebSocket query 参数里解析 options 并传入：

```python
# room/room_manager.py — connect()

async def connect(self, ws: WebSocket, room_name: str, user_id: str, display_name: str,
                  options: dict | None = None) -> None:
    ...
    # 房间不存在 → 创建
    await self._create_room(ws, room_name, user_id, display_name, options)
```

在 `app.py` 的 WebSocket 端点里解析 query 参数并传入：

```python
# app.py — WebSocket 端点

@app.websocket("/ws/{room_name}")
async def ws_endpoint(
    ws: WebSocket,
    room_name: str,
    token: str = Query(""),
    turn_time_limit: int = Query(0),   # ← 新增
):
    ...
    options = {"turn_time_limit": turn_time_limit}
    await room_manager.connect(ws, room_name, user_id, display_name, options=options)
```

### Step 3 — room_manager.py：在每回合开始时启动/取消定时器

定时器系统已经预留了 `action:{room_name}:{user_id}` 这个 key（见 `timeout_scheduler.py` 注释）。

在 `_handle_game_action()` 里，**每次游戏层处理完后**，根据当前轮到的玩家重新挂载定时器：

```python
# room/room_manager.py — _handle_game_action() 末尾

# ── 回合超时定时器 ──────────────────────
turn_time = room.turn_time_limit
if turn_time > 0 and not round_just_ended:
    # 取消旧定时器（防止重复）
    await self.timers.cancel(f"action:{room_name}:{user_id}")

    # 找到下一个轮到的玩家
    next_player_id = game.current_player_id   # 假设 game 提供此属性

    timer_key = f"action:{room_name}:{next_player_id}"
    await self.timers.schedule(
        timer_key,
        turn_time,
        self._on_turn_timeout,
        room_name, next_player_id,
    )
```

实现超时回调——超时后代替玩家执行一个合法动作（例如打出手中第一张牌）：

```python
async def _on_turn_timeout(self, room_name: str, user_id: str) -> None:
    """回合超时：代替玩家自动出牌"""
    room = self.rooms.get(room_name)
    if room is None or room.status != RoomStatus.RUNNING:
        return

    game = self.games.get(room_name)
    if game is None or not game.is_running:
        return

    # 通知双方超时
    await self.push.broadcast(room_name, protocol.make_turn_timeout(user_id))

    # 自动执行 discard（打出第一张手牌）
    await self._handle_game_action(room, action="discard", card_idx=0, user_id=user_id)
    logger.info("回合超时自动出牌 [%s] 玩家=%s", room_name, user_id[:8])
```

**别忘了在房间销毁时取消定时器。** `cleanup_room()` 里已经有 `cancel_prefix("action:{room_name}")` 的调用位置，按照已有模式加一行即可：

```python
# room/room_manager.py — cleanup_room()
await self.timers.cancel_prefix(f"action:{room_name}")   # 已存在，确认包含即可
```

### Step 4 — protocol.py：定义超时通知消息

```python
# room/protocol.py

def make_turn_timeout(user_id: str) -> dict:
    """回合超时通知（广播）"""
    return {
        "broadcast": True,
        "event": "turn_timeout",
        "user_id": user_id,
    }
```

消息分两类：
- `"broadcast": True` → 用 `self.push.broadcast(room_name, msg)` 发给房间所有人
- `"broadcast": False` → 用 `self.push.unicast(room_name, user_id, msg)` 只发给特定玩家

### Step 5 — ws.ts：前端处理新事件

在 [web-svelte/src/lib/ws.ts](../web-svelte/src/lib/ws.ts) 的 `handleBroadcastEvent()` 里加一个 case：

```typescript
case "turn_timeout":
    // 显示超时提示，然后游戏状态会随后一条 unicast 消息更新
    addLog(`玩家 ${data.user_id} 回合超时，自动出牌`);
    break;
```

如果前端需要展示倒计时，还需要在收到 `game_started` 和每次收到对手操作后重置计时器。可以把 `room.config.turn_time_limit` 随 `game_started` 事件一起下发给客户端：

```python
# room_manager.py — _send_game_start_state() 里
info = {
    ...
    "turn_time_limit": room.turn_time_limit,   # ← 新增
}
```

### Step 6 — 同步 AsyncAPI 文档

修改 `docs/asyncapi.yaml` 和 `docs/asyncapi.zh.yaml`（两个都要改，内容结构相同只是语言不同）：

```yaml
# 1. 新增 action（如果有的话）— 无，本例不新增客户端 action

# 2. 新增服务端事件
components:
  messages:
    TurnTimeoutMessage:
      payload:
        type: object
        properties:
          broadcast: { type: boolean, const: true }
          event: { type: string, const: turn_timeout }
          user_id: { type: string }

# 3. 在 channel 的 subscribe.oneOf 里引用新消息
channels:
  /ws/{room_name}:
    subscribe:
      message:
        oneOf:
          - $ref: '#/components/messages/TurnTimeoutMessage'  # ← 新增

# 4. 更新 GameStartedPayload，加入 turn_time_limit 字段
components:
  schemas:
    GameStartedPayload:
      properties:
        turn_time_limit:
          type: integer
          description: 每回合时间上限（秒），0 表示不限时
```

---

## 4. 对局规则（game.py 侧）

对局规则（点数计算、役种）不属于房间模块，你只需要把参数透传进去：

```python
# room/room_manager.py — _start_game()

game = ChinitsuGame(rules={
    "initial_point": room.config.get("initial_point", 150_000),
    "no_agari_punishment": room.config.get("no_agari_punishment", 20_000),
    "yaku_rules": {
        "has_daisharin": room.config.get("has_daisharin", False),
    },
})
```

`game.py` 的 `default_rules` 会自动填充你没有传的字段（`rules.update(...)` 逻辑）。如果要新增对局规则，在 `game.py` 的 `default_rules` 里加默认值，然后在 `set_rules()` 里处理即可——这不是你的代码范围，告诉负责 game.py 的同事按这个模式加就行。

---

## 5. 关键文件速查

| 要改什么 | 改哪里 | 关键方法 |
|---|---|---|
| 房间规则字段 | [models.py](../server/room/models.py) | `Room` dataclass + `to/from_redis_dict` |
| 创建房间时读取规则 | [room_manager.py](../server/room/room_manager.py) | `_create_room()` |
| 客户端 action 路由 | [room_manager.py](../server/room/room_manager.py) | `handle_action()` 状态分发块 |
| 定时器（超时） | [timeout_scheduler.py](../server/room/timeout_scheduler.py) | `schedule()` / `cancel()` |
| 服务端消息格式 | [protocol.py](../server/room/protocol.py) | `make_xxx()` 工厂函数 |
| 错误码 | [errors.py](../server/room/errors.py) | WS_CLOSE_* / ERR_* 常量 |
| 对局规则透传 | [room_manager.py](../server/room/room_manager.py) | `_start_game()` 里 `ChinitsuGame(rules=...)` |
| 前端消息处理 | [ws.ts](../web-svelte/src/lib/ws.ts) | `handleBroadcastEvent()` |
| WebSocket 入口 | [app.py](../server/app.py) | `ws_endpoint()` Query 参数 |
| 协议文档 | [asyncapi.yaml](asyncapi.yaml) / [asyncapi.zh.yaml](asyncapi.zh.yaml) | 两个都改 |

---

## 6. 规范与注意事项

### 必须做

**① Redis 序列化要同步**
每次在 `Room` 上加字段，必须同步更新 `to_redis_dict()` 和 `from_redis_dict()`，并在 `from_redis_dict()` 里写好默认值。漏掉一个会导致服务重启或玩家重连后字段丢失/类型报错。

**② 规则只在创建时写入**
`_create_room()` 是唯一写 `room.config`（或各规则字段）的地方。其他方法（`_handle_start`、`_handle_game_action` 等）只读不写。这样保证对局中规则不会变化。

**③ 定时器要成对管理**
`schedule()` 和 `cancel()` 必须成对出现：
- 触发某条件 → `schedule(...)`
- 收到对应 action → `cancel(...)` 取消
- 房间销毁 → `cleanup_room()` 里 `cancel_prefix(...)` 批量清理

**④ 状态机前置检查**
`handle_action()` 里已按 `room.status` 分发，你的新 handler 只会在特定状态下被调用，不用再重复检查。但如果你的逻辑涉及跨状态（比如定时器回调，可能在状态已经变化后才触发），要在回调开头检查 `room.status`。

**⑤ 两份 AsyncAPI 文档都要改**
`asyncapi.yaml`（英文）和 `asyncapi.zh.yaml`（中文）内容结构完全相同，任何协议变动都需要同步修改两个文件。

### 开发效率建议

**批量添加规则，用 config 字典而不是散字段**
规则多了之后，比起每条规则单独加字段，用一个 `config: dict` 统一管理的好处是：
- Redis 序列化只有一行 `json.dumps(self.config)`，加规则不改序列化代码
- 前端传参格式统一：`{"action": "start", "config": {"round_limit": 4, "turn_time_limit": 30}}`
- 协议文档里只需更新 `RoomConfig` schema 一处

**写测试时用 helpers.py 里的工厂函数**
`server/room/tests/helpers.py` 提供了 `make_room()` / `make_session()` 快速构造测试对象，新规则字段也在这里加默认值，避免每个测试用例都手动设置。

**用已有定时器 key 约定**
`timeout_scheduler.py` 里注释了现有的 key 命名约定：
```
room_expire:{room_name}        # 房间 40 分钟寿命
reconnect:{room_name}:{uid}    # 断线重连超时
skip_ron:{room_name}           # AFTER_DISCARD 等待
action:{room_name}:{uid}       # 行动超时（已预留，未实现）
```
新的回合类定时器遵循 `action:` 前缀，销毁时自动被 `cancel_prefix` 清理。

### 每次改动的 checklist

```
□ models.py — 加字段 / 加常量 / 更新 to_redis_dict + from_redis_dict
□ room_manager.py — _create_room() 读取规则；相关 handler 使用规则
□ protocol.py — 如有新消息，加 make_xxx() 函数
□ app.py — 如有新 Query 参数，在 ws_endpoint() 里声明
□ ws.ts — handleBroadcastEvent() 加对应 case
□ asyncapi.yaml + asyncapi.zh.yaml — 同步更新（两个都改）
□ tests/ — 补充对应测试用例
```
