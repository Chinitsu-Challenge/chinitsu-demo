# 旁观模式设计方案

> 状态：草稿 | 版本：v0.1 | 日期：2026-04-09

---

## 1. 业务需求

### 1.1 目标

允许已有账号的用户以"旁观者"身份加入一个已满员（2 名游戏玩家）的房间，实时观看对局过程，获得比游戏玩家更完整的信息视角。

### 1.2 功能需求

**旁观者能做的事**
- 连接到任意处于 WAITING / RUNNING / RECONNECT / ENDED 状态的房间（含满员房间）
- 实时接收房间内的所有事件（玩家动作、状态变更、房间通知）
- 查看双方完整手牌、牌山数量、双方河牌、副露、点数
- 查看胡牌时的完整信息（役种、番数、符数、得失点）
- 随时离开，不影响对局

**旁观者不能做的事**
- 发送任何游戏动作（draw / discard / riichi / ron 等）
- 参与投票（start / continue_game / end_game）
- 触发房间状态机的任何转移
- 影响断线重连逻辑（旁观者断线不触发 RECONNECT）

### 1.3 非功能需求

- 旁观者数量上限：每个房间最多 **10 名**旁观者（防止滥用）
- 旁观者不持久化到 Redis（重连就是重新加入，没有会话恢复）
- 同一账号同时只能旁观一个房间（与现有一房间一玩家的限制对齐，但玩家身份和旁观者身份互斥）

---

## 2. 职责边界

### 2.1 需要修改的文件

| 文件 | 改动内容 | 改动幅度 |
|---|---|---|
| `room/models.py` | 新增 `SpectatorSession` dataclass | 小 |
| `room/room_manager.py` | `connect()` 新增旁观分支；`disconnect()` 新增旁观清理；`_handle_game_action()` 新增旁观推送 | 中 |
| `room/push_service.py` | 新增旁观连接池；新增 `broadcast_spectators()` / `unicast_spectator()` | 中 |
| `room/snapshot_manager.py` | 新增 `build_spectator_view()` | 小 |
| `room/protocol.py` | 新增 `make_spectator_joined()` / `make_spectator_left()` / `make_spectator_snapshot()` | 小 |
| `room/errors.py` | 新增 `WS_CLOSE_SPECTATOR_ROOM_FULL` / `ERR_SPECTATOR_ACTION_FORBIDDEN` | 小 |
| `server/app.py` | `ws_endpoint()` 无需改动（connect 内部处理） | 无 |
| `docs/asyncapi.yaml` + `.zh.yaml` | 新增旁观相关事件和 schema | 中 |
| `web-svelte/src/lib/ws.ts` | 新增旁观事件处理；新增旁观 UI 状态 | 中 |
| `web-svelte/src/routes/+page.svelte` | 新增旁观者视图组件入口 | 中 |

### 2.2 不需要修改的文件

| 文件 | 原因 |
|---|---|
| `room/state_machine.py` | 旁观者对状态机完全透明，不触发任何事件 |
| `room/reconnect_manager.py` | 旁观者无重连逻辑，断线即离开 |
| `room/ready_service.py` | 旁观者不参与投票 |
| `room/end_decision_service.py` | 同上 |
| `room/match_end_evaluator.py` | 不涉及 |
| `room/timeout_scheduler.py` | 无新定时器需求 |
| `game.py` | 游戏层完全不感知旁观者 |

---

## 3. 数据模型

### 3.1 SpectatorSession（新增 dataclass）

```python
# room/models.py
@dataclass
class SpectatorSession:
    user_id: str           # 来自 JWT 的 UUID
    display_name: str      # 昵称
    room_name: str         # 所在房间
    ws: "WebSocket | None" = None
    joined_at: float = field(default_factory=time.time)
```

与 `PlayerSession` 的关键区别：
- **不持久化**：无 `to_redis_dict()` / `from_redis_dict()`
- **无在线/离线状态**：断线即移除，不保留会话
- **无 `connection_id`**：无需防旧连接误触发

### 3.2 RoomManager 新增存储

```python
# room/room_manager.py
self.spectators: dict[str, dict[str, SpectatorSession]] = {}
# 结构：{room_name: {user_id: SpectatorSession}}
```

`self.sessions`（玩家）和 `self.spectators`（旁观者）**完全分离**，现有所有对 `self.sessions` 的读写逻辑零修改。

---

## 4. 连接流程

### 4.1 旁观者进入房间的判定条件

在 `connect()` 中，判断为旁观者的时机：**现有所有玩家重连/加入检查都通过后，遇到满员（`room.is_full`）时，不拒绝，而是走旁观分支**。

```
connect() 入口
│
├─ 场景 1：RECONNECT 中离线玩家 → 重连 (现有逻辑)
├─ 场景 1b：ENDED 中离线玩家 → 恢复 (现有逻辑)
├─ 场景 1c：WAITING 中离线玩家 → 恢复 (现有逻辑)
├─ 一房间一玩家限制检查 (现有逻辑，旁观者也受此约束*)
│
├─ 场景 2：房间存在
│   ├─ 满员？
│   │   └─ [新] 旁观者上限检查 → accept → _join_as_spectator()  ← 新分支
│   └─ 未满 → 现有逻辑（加入房间）
│
└─ 场景 3：房间不存在 → 创建房间 (现有逻辑)
```

> \* 一房间一账号限制：`get_user_active_room()` 只扫描 `self.sessions`（玩家）。旁观者用 `get_user_spectating_room()` 另行扫描 `self.spectators`。两者互斥：已是玩家不能旁观同一房间，已在旁观不能再旁观别的房间。

### 4.2 `_join_as_spectator()` 逻辑

```
1. 检查旁观者数量上限（>= 10 → 关闭连接，WS_CLOSE_SPECTATOR_ROOM_FULL）
2. accept WebSocket
3. 创建 SpectatorSession，加入 self.spectators[room_name]
4. 广播 spectator_joined 给房间内所有人（玩家 + 其他旁观者）
5. 推送 spectator_snapshot 给新旁观者（当前完整游戏状态）
```

### 4.3 旁观者断线

`disconnect()` 中先在 `self.spectators` 查找，找到则走旁观路径：

```
1. 从 self.spectators[room_name] 移除
2. 广播 spectator_left 给房间内所有人
3. 完成（无状态机转移，无 Redis 操作，无定时器）
```

---

## 5. 消息协议

### 5.1 新增服务端事件

所有新事件均广播给房间内**所有人**（玩家 + 旁观者），旁观者自己的加入/离开也不例外。

| 事件名 | 触发时机 | 接收方 | 关键字段 |
|---|---|---|---|
| `spectator_joined` | 旁观者加入 | 全部（broadcast） | `display_name`, `spectator_count` |
| `spectator_left` | 旁观者离开 | 全部（broadcast） | `display_name`, `spectator_count` |
| `spectator_snapshot` | 旁观者加入时/请求刷新 | 单播给旁观者 | 见 §5.2 |
| `spectator_game_update` | 游戏层每次 action 处理后 | 广播给所有旁观者 | 见 §5.2 |

游戏层原有的 unicast 消息（发给玩家的 `game_snapshot`、`draw` 结果等）**不改变**，旁观者通过独立的 `spectator_game_update` 获取信息。

### 5.2 旁观者视角 payload（`spectator_snapshot` / `spectator_game_update`）

旁观者是全知视角，payload 暴露双方完整信息：

```json
{
  "event": "spectator_snapshot",
  "broadcast": false,
  "game_status": "running",
  "turn_stage": "after_draw",
  "current_player": "<user_id>",
  "turn_number": 5,
  "round_no": 2,
  "round_limit": 8,
  "wall_count": 48,
  "wall": ["1m", "2m", ...],        // 旁观者可看牌山（可选，见 §6）
  "kyoutaku_number": 0,
  "tsumi_number": 0,
  "players": {
    "<user_id_A>": {
      "display_name": "Alice",
      "hand": ["1m", "2m", "3m", ...],   // 完整手牌（玩家视角会隐藏对手手牌）
      "fuuro": [...],
      "kawa": [...],
      "point": 148000,
      "is_oya": true,
      "is_riichi": false,
      "num_kan": 0
    },
    "<user_id_B>": { ... }
  }
}
```

与玩家收到的 `game_snapshot` 的差异：
- `players` 中两名玩家都有完整 `hand`（玩家视角对手只有 `hand_count`）
- 额外字段 `wall`（可选，见 §6 讨论）
- 无 `me` / `opponent` 区分，直接用 `players` 字典

### 5.3 旁观者的动作处理

旁观者发送任何 action → 返回错误，不关闭连接：

```json
{ "event": "error", "code": "spectator_action_forbidden" }
```

在 `handle_action()` 入口处，先判断发送方是否为旁观者，是则直接 unicast 错误并 return。

### 5.4 胡牌信息

胡牌时游戏层返回的结果（`yaku`、`han`、`fu`、`point`）目前以 unicast 发给双方玩家。  
旁观者需要独立地在 `spectator_game_update` 中收到含胡牌详情的完整结果，或通过收到最新快照（快照会在胡牌后保存）来获取。  
具体实现时，最简单的方式是：游戏 action 处理完→保存快照→广播 `spectator_game_update`（包含快照全量信息）。

---

## 6. 待决议的问题（已确认）

以下几点需要在实现前确认：

| # | 问题 | 建议默认值 |
|---|---|---|
| 1 | **是否暴露牌山具体内容**？（还是只显示 `wall_count`） | 先只暴露 `wall_count`；后续可配置 |
| 2 | **WAITING 状态是否允许旁观**？（对局未开始，没什么可看） | 允许，旁观者进入后等待游戏开始 |
| 3 | **ENDED 状态是否允许新旁观者加入**？（只能看到最终分数） | 允许，发送末局快照 |
| 4 | **旁观者是否显示彼此**？（旁观者、玩家间能否看到谁在旁观） | 是，`spectator_joined/left` 广播给所有人 |
| 5 | **旁观者数量上限是否可配置**？ | 先写死 10，之后可加入 `Room.config` |
| 6 | **玩家能否主动踢出旁观者**？ | 本期不做 |
| 7 | **旁观者能否发弹幕/评论**？ | 本期不做 |

---

## 7. 实施步骤（建议顺序）

### Step 1 — 后端数据层（models.py、errors.py）
- 新增 `SpectatorSession` dataclass
- 新增错误码 `WS_CLOSE_SPECTATOR_ROOM_FULL`、`ERR_SPECTATOR_ACTION_FORBIDDEN`

### Step 2 — 推送层（push_service.py）
- RoomManager 增加 `self.spectators` 存储
- PushService 接收 `spectators_store` 引用，新增：
  - `broadcast_spectators(room_name, payload)` — 广播给所有在线旁观者
  - `broadcast_all(room_name, payload)` — 广播给玩家 + 旁观者
  - `unicast_spectator(room_name, user_id, payload)` — 单播给旁观者
- 更新 `close_all_connections()` 也关闭旁观者连接

### Step 3 — 快照视角（snapshot_manager.py）
- 新增 `build_spectator_view(snapshot)` — 返回全知视角 payload（无裁剪，双方手牌均暴露）

### Step 4 — 消息工厂（protocol.py）
- 新增 `make_spectator_joined(display_name, spectator_count)`
- 新增 `make_spectator_left(display_name, spectator_count)`
- 新增 `make_spectator_snapshot(snapshot)` (直接调用 build_spectator_view)

### Step 5 — 连接/断线逻辑（room_manager.py）
- 新增 `get_user_spectating_room(user_id)` 工具方法
- `connect()` 在满员判断处新增旁观分支（调用 `_join_as_spectator()`）
- 新增 `_join_as_spectator(ws, room, user_id, display_name)`
- `disconnect()` 新增旁观者路径（优先在 `self.spectators` 查找）
- `handle_action()` 入口新增旁观者拦截
- `_handle_game_action()` 末尾新增 `broadcast_spectators(spectator_game_update)`
- `cleanup_room()` 新增旁观者连接的关闭和清理

### Step 6 — 协议文档（asyncapi.yaml / asyncapi.zh.yaml）
- 新增 `SpectatorSession` schema（player_count、spectator_count 字段）
- 新增 4 个 message（spectator_joined / spectator_left / spectator_snapshot / spectator_game_update）
- 新增错误码 `spectator_action_forbidden`
- 更新 `ErrorCode` enum

### Step 7 — 前端（web-svelte）
- `ws.ts`：新增旁观者事件处理（spectator_joined / spectator_left / spectator_snapshot / spectator_game_update）
- 新增 `isSpectator` 状态标识
- 新增 `SpectatorGame` 组件（展示双方手牌、牌山信息，隐藏操作按钮）
- `+page.svelte`：根据 `isSpectator` 路由到旁观视图

### Step 8 — 测试
- 测试旁观者加入满员房间
- 测试旁观者不影响游戏动作（玩家动作后旁观者收到更新）
- 测试旁观者断线不影响房间状态
- 测试房间销毁时旁观者连接被正确关闭
- 测试旁观者数量上限

---

## 8. 关键设计决策与理由

### 为什么用独立的 `self.spectators` 而不是扩展 `PlayerSession`

在 `PlayerSession` 里加一个 `role: Literal["player", "spectator"]` 字段看起来更简单，但会把旁观逻辑散布到现有的所有 if/else 中（`reconnect_manager`、`ready_service`、`match_end_evaluator` 都需要跳过旁观者），风险极高。独立存储让**现有代码零修改**，代价只是在 `connect/disconnect/handle_action` 的入口处多一层路由。

### 为什么旁观者不持久化到 Redis

旁观者的参与是轻量级的：断线即离开，重新连接就是重新加入，拿一次新的全量快照即可。持久化旁观者会话带来的复杂度远高于收益。

### 为什么游戏层的 unicast 不改，而是单独发 `spectator_game_update`

游戏层的 unicast 消息（如 `draw` 结果中含有摸到的牌）目前设计为"只发给当事玩家"，改动它会影响隐私逻辑。旁观者通过独立的全量快照更新获取信息，两条通道互不干扰。
