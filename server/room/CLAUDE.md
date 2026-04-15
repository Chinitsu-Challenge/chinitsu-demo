# CLAUDE.md — room 模块

本文件为 Claude Code 及协作者提供 `server/room/` 模块的完整背景。

---

## 模块职责

`room/` 是游戏房间的完整生命周期管理层，负责：

- 玩家连接/断线/重连的路由与会话维护
- 房间状态机（WAITING → RUNNING → RECONNECT → ENDED → DESTROYED）
- Redis 持久化（房间、会话、游戏快照）
- 对局规则透传到游戏层（`game.py`）
- 定时任务管理（房间寿命、重连超时、自动 skip_ron）

`app.py` 的 WebSocket 路由**只与 `RoomManager` 交互**，其他类均为内部组件。

---

## 文件结构

```
room/
├── models.py            # 数据模型：Room、PlayerSession、SpectatorSession、常量
├── state_machine.py     # 纯函数状态机：合法转移表 + transition() / can_transition()
├── errors.py            # 错误码：WS_CLOSE_* 关闭码、ERR_* JSON 业务错误码、异常类
├── protocol.py          # 消息工厂：make_xxx() 纯函数，生成标准推送消息字典
├── room_manager.py      # 主协调器：connect / disconnect / handle_action，组合所有子服务
├── reconnect_manager.py # 断线重连：离线标记、RECONNECT 状态转移、超时判负
├── snapshot_manager.py  # 快照管理：序列化游戏对象、Redis 存取、玩家/旁观者视角裁剪
├── push_service.py      # 推送服务：broadcast（玩家+旁观者）/ unicast / 旁观者专用方法
├── timeout_scheduler.py # 定时器：asyncio.Task 封装，按 key 增删，支持前缀批量取消
├── ready_service.py     # 开始投票：双方 start 确认逻辑（WAITING / 轮次间）
├── end_decision_service.py  # 结束投票：continue_game / end_game 双方确认逻辑
├── match_end_evaluator.py   # 比赛终止评估：点数<0 / 轮数达上限
└── tests/
    ├── conftest.py      # pytest 配置：sys.path 设置 + no_redis autouse fixture
    ├── helpers.py       # 测试工厂：make_room() / make_session() / setup_two_player_room() / run_async()
    ├── test_reconnect_manager.py
    ├── test_room_manager.py
    ├── test_spectator.py
    ├── test_push_service.py
    ├── test_service_units.py
    ├── test_state_machine.py
    └── test_timeout_scheduler.py
```

---

## 核心数据模型

### 房间状态机

```
[空] ──CREATE──▶ WAITING ──BOTH_READY──▶ RUNNING ──MATCH_END──▶ ENDED
                    │                       │                      │
                 ALL_LEFT            PLAYER_DISCONNECT         BOTH_CONTINUE
                    │                       │                      │ (回 WAITING)
                    ▼               RECONNECT ──PLAYER_RECONNECT──▶ RUNNING
                DESTROYED               │
                    ▲           RECONNECT_TIMEOUT ──▶ ENDED
                    │           BOTH_OFFLINE ──▶ DESTROYED
              ROOM_EXPIRED（任意状态均可到 DESTROYED）
```

状态转移通过 `state_machine.transition(current, event)` 执行，非法转移抛 `InvalidTransitionError`。所有转移在 `room_manager._do_transition()` 里统一记录日志并同步 Redis。

### RoomStatus 语义

| 状态 | 含义 |
|---|---|
| `WAITING` | 等待双方加入/确认开始；单人或双人均可处于此状态 |
| `RUNNING` | 对局进行中；包含多轮，单轮结束后状态仍为 RUNNING |
| `RECONNECT` | 一方断线，等待 120 秒重连；对局暂停，拒绝所有游戏动作 |
| `ENDED` | 整场比赛结束；等待双方投票 continue / end |
| `DESTROYED` | 终态，仅内存标记，实际数据已清理 |

### Room dataclass（`models.py`）

关键字段：

```python
room_id: str          # UUID，用于定时器幂等保护（防止误删同名新房间）
room_name: str        # 客户端指定的名称（URL 路径参数）
status: RoomStatus
player_ids: list[str] # 按入座顺序，最多 2 个
round_no: int         # 已完成的轮数
round_limit: int      # 比赛轮数上限（默认 8）
```

`room_id` 的作用：定时器回调时用 `room.room_id != saved_room_id` 判断是否已是新房间，避免误杀。

### PlayerSession dataclass（`models.py`）

```python
user_id: str          # 来自 JWT 的 UUID
connection_id: str    # 每次建立连接时重新生成，用于区分新旧连接
online: bool          # 当前是否在线
ws: WebSocket | None  # 不参与 Redis 序列化
```

`connection_id` 的作用：`on_disconnect` 收到旧连接的事件时，通过比对 `session.connection_id` 判断是否需要忽略，防止重连后旧 disconnect 事件误伤新连接。

### SpectatorSession dataclass（`models.py`）

```python
user_id: str          # 来自 JWT 的 UUID
display_name: str
room_name: str
ws: WebSocket | None  # 不持久化，不参与 Redis 序列化
joined_at: float      # 加入时间戳
```

旁观者**没有** `connection_id`、`online` 字段，不走重连流程。断线即移除。

### 默认常量（`models.py`）

```python
ROOM_MAX_LIFETIME_SEC    = 40 * 60   # 房间绝对寿命
RECONNECT_TIMEOUT_SEC    = 120       # 断线重连超时
SKIP_RON_TIMEOUT_SEC     = 30        # AFTER_DISCARD 等待超时
DEFAULT_ROUND_LIMIT      = 8         # 默认比赛轮数上限
MAX_SPECTATORS_PER_ROOM  = 10        # 单房间旁观者上限
```

---

## 关键机制

### Redis 持久化

房间和会话数据存两份：内存（`self.rooms` / `self.sessions`）+ Redis Hash。  
Redis 用于服务重启恢复（目前未实现启动时恢复，但数据已持久化备用）。

- `Room.to_redis_dict()` / `from_redis_dict()` — 所有字段都序列化为字符串
- `PlayerSession.to_redis_dict()` — 同上，`ws` 字段不参与序列化
- 每次修改 Room 或 Session 字段后，必须调用：
  - `await self._sync_room_to_redis(room)`
  - `await self._sync_session_to_redis(session)`

**新增字段时必须同步更新 `to_redis_dict()` 和 `from_redis_dict()`，并在 `from_redis_dict()` 中写好默认值。**

### 断线重连（`reconnect_manager.py`）

按房间状态分四条路径：

| 断线时状态 | 处理行为 |
|---|---|
| `RUNNING` | 标记离线 → 切 RECONNECT → 启 120s 计时器 → 通知对手 |
| `RECONNECT` | 再次断线 → 若双方均离线 → 销毁房间 |
| `WAITING`（2 人）| 标记离线，保留会话（等重连）；清空开始投票；双方都离线则销毁 |
| `WAITING`（1 人）| 直接移除玩家；若房间空了则销毁 |
| `ENDED` | 仅标记离线，保留会话和投票记录 |

重连（`on_reconnect()`）只处理 RECONNECT 状态。ENDED 和 WAITING 的"重连"（实际是恢复离线会话）在 `room_manager.connect()` 的前置检查里处理（scenario 1b / 1c）。

### 快照（`snapshot_manager.py`）

快照 = 序列化后的完整游戏状态（包含双方明文手牌）。

- 存储：`serialize_game()` → `save_snapshot(room_name, snapshot)`（Redis + 内存兜底）
- 玩家视角：`build_player_view(snapshot, user_id)` — 裁剪对手手牌后 unicast 给玩家
- 旁观者视角：`build_spectator_view(snapshot)` — 双方手牌全部暴露，event 为 `spectator_snapshot`

**注意**：AFTER_DISCARD 阶段，快照中的 `current_player` 存的是刚打牌的一方，但前端期望的是"当前可以行动的一方"（即可以 ron/skip 的对手）。`build_player_view()` 和 `build_spectator_view()` 均有此翻转处理：

```python
if turn_stage == "after_discard" and len(all_pids) == 2:
    frontend_current_player = next(pid for pid in all_pids if pid != raw_current)
```

### 定时器（`timeout_scheduler.py`）

所有定时任务通过 `TimeoutScheduler` 管理，按 key 标识：

| Key 格式 | 触发场景 |
|---|---|
| `room_expire:{room_name}` | 房间 40 分钟绝对寿命 |
| `reconnect:{room_name}:{user_id}` | 断线重连 120s 超时 |
| `skip_ron:{room_name}` | AFTER_DISCARD 等待 30s 自动 skip_ron |
| `action:{room_name}:{user_id}` | 回合行动超时（已预留，待实现） |

房间销毁时，`cleanup_room()` 用 `cancel_prefix(f"...")` 批量取消所有相关定时器。

### 旁观者模式（`room_manager.py`）

`RoomManager` 维护独立的旁观者存储：

```python
self.spectators: dict[str, dict[str, SpectatorSession]] = {}
```

**连接路由**（`connect()` 入口，按优先级顺序）：

1. 无效房间名 → 拒绝
2. 同账号已在此房间在线（`duplicate_id`）→ 拒绝
3. 同账号已在**另一**房间旁观 → 拒绝（`already_in_room`）
4. 同账号已在**另一**房间作为玩家 → 拒绝（`already_in_room`）
5. 房间已满（2 名玩家）→ `_join_as_spectator()`
6. 正常加入/创建房间

**旁观者加入流程**（`_join_as_spectator()`）：
- 超出 `MAX_SPECTATORS_PER_ROOM` → 关闭 `spectator_room_full`
- 广播 `spectator_joined`（玩家 + 所有旁观者均收到）
- 若游戏进行中：unicast `spectator_snapshot`（全知视角）
- 若 WAITING：unicast `spectator_snapshot`（`players: {}`，game_status: waiting）

**旁观者动作拦截**（`handle_action()` 最顶部）：
任何来自旁观者的 action 直接返回 `ERR_SPECTATOR_ACTION_FORBIDDEN`，不进入状态机。

**游戏更新推送**（`_push_spectator_update()`）：
每次 `_start_game()` / `_start_next_round()` / `_handle_game_action()` 后调用，
broadcast `spectator_game_update` 给所有旁观者。

### `broadcast()` 的语义

`PushService.broadcast()` **同时覆盖玩家和旁观者**，所有现有调用点无需修改。

| 方法 | 接收方 |
|---|---|
| `broadcast(room, payload)` | 在线玩家 + 所有旁观者 |
| `broadcast_players(room, payload)` | 仅在线玩家 |
| `broadcast_spectators(room, payload)` | 仅旁观者 |
| `unicast(room, user_id, payload)` | 指定玩家 |
| `unicast_spectator(room, user_id, payload)` | 指定旁观者 |

### 一房间一用户限制

`get_user_active_room(user_id)` 扫描 `self.sessions`（玩家身份）。  
`get_user_spectating_room(user_id)` 扫描 `self.spectators`（旁观者身份）。  
`connect()` 入口同时检查两者，拒绝跨房间或身份混用。

例外：若找到的房间就是本次要连接的房间（ENDED/WAITING 重连场景），则走重连流程，不拒绝。

---

## 对外接口（`room_manager.py`）

`app.py` 只调用三个方法：

```python
await room_manager.connect(ws, room_name, user_id, display_name)
await room_manager.disconnect(ws, room_name, user_id)
await room_manager.handle_action(data, room_name, user_id)
```

### `handle_action()` 路由规则

**第 0 步（最优先）**：检测是否旁观者 → 是则直接返回 `ERR_SPECTATOR_ACTION_FORBIDDEN`。

之后按 `room.status` 分发：

| 状态 | 合法 action |
|---|---|
| `WAITING` | `start` / `start_new`、`cancel_start`、`leave_room` |
| `RUNNING` | `start` / `start_new`（轮次间重启）、游戏动作（draw/discard/riichi/kan/tsumo/ron/skip_ron） |
| `ENDED` | `continue_game`、`end_game`、`leave_room`、`start` / `start_new`（兼容映射到 continue_game） |
| `RECONNECT` | 所有 action 均返回 `ERR_GAME_PAUSED` |

---

## 错误码（`errors.py`）

```
WS_CLOSE_*   →  WebSocket 关闭码，强制断开连接
ERR_*        →  JSON 消息 {"event": "error", "code": "..."}，不断连接
```

新增错误码在 `errors.py` 统一定义，避免魔法字符串散落各处。同时需更新 `docs/asyncapi.yaml` 和 `docs/asyncapi.zh.yaml` 的 `ErrorCode` schema。

---

## 消息格式（`protocol.py`）

所有服务端推送消息通过 `protocol.make_xxx()` 工厂函数生成，字段结构统一：

```python
{
    "broadcast": True/False,   # True = 广播给房间所有人，False = 单播
    "event": "event_name",
    ...                        # 事件特定字段
}
```

- 广播：`self.push.broadcast(room_name, protocol.make_xxx(...))`
- 单播：`self.push.unicast(room_name, user_id, protocol.make_xxx(...))`

新增事件先在 `protocol.py` 加工厂函数，再更新 AsyncAPI 文档。

---

## 测试

两套测试套件均注册在 `pyproject.toml` 的 `testpaths` 中，从项目根目录运行：

```bash
uv run pytest -v          # 同时跑集成测试（tests/）+ 房间单元测试（server/room/tests/）
```

**测试隔离**：`conftest.py` 的 `_no_redis` fixture（autouse）将所有 `get_redis` 调用 patch 为 `None`，确保单元测试完全跑内存路径，不受全局 Redis 单例污染。

> **背景**：`redis_client._client` 是模块级全局单例。若集成测试初始化了 Redis 连接，且前一个单元测试往 Redis 写入了 "testroom" 快照，后续新建 `RoomManager` 实例时 `load_snapshot()` 仍会读到该快照，导致测试相互干扰。

`helpers.py` 提供：
- `make_room(room_name, status, player_ids)` — 快速构造 Room 对象
- `make_session(user_id, room_name, online)` — 快速构造 PlayerSession 对象
- `setup_two_player_room(room_name)` — 创建 RoomManager + 连入两名玩家，返回 WAITING 状态
- `setup_running_room(room_name, debug_code)` — 在 `setup_two_player_room` 基础上双方 start，返回 RUNNING 状态
- `run_async(coro)` — 执行异步协程（内部用 `asyncio.run()`）

---

## 增量开发指引

详见 [`docs/room-module-dev-guide.md`](../../docs/room-module-dev-guide.md)。

简要 checklist：

```
□ models.py       — 新字段 + 同步 to_redis_dict / from_redis_dict（含默认值）
□ room_manager.py — _create_room() 读取规则；handle_action() 加分支；新 handler 方法
□ protocol.py     — 新事件加 make_xxx() 工厂函数
□ errors.py       — 新错误码在此集中定义
□ app.py          — 新 Query 参数在 ws_endpoint() 声明
□ ws.ts           — handleBroadcastEvent() 加对应 case
□ asyncapi.yaml + asyncapi.zh.yaml — 两个文件同步更新
□ tests/          — 补充对应测试用例
```

### 扩展旁观者功能的 checklist

```
□ 旁观者聊天/反应     — handle_action() 顶部旁观者拦截改为白名单；protocol.py 加 make_spectator_chat()
□ 旁观者人数显示给玩家 — build_player_view() 加 spectator_count 字段；types.ts / GameState 同步
□ 旁观者重连          — SpectatorSession 加 to_redis_dict()；connect() 加旁观者重连路径
□ 踢出旁观者          — errors.py 加错误码；handle_action() 加 kick_spectator 分支（仅房主可用）
```
