# 房间模块测试中发现的问题

> 初次记录：2026-04-02 | 最后更新：2026-04-02（修复批次 1）

---

## Issue #1：流局（Ryuukyoku）后无法开始下一轮 ⚠️ 待修复

**文件**：`server/room/room_manager.py` — `_handle_round_restart()`  
**严重程度**：高（功能阻断）  
**状态**：**未修复**（涉及 game.py 游戏逻辑，超出本次修复范围）

**描述**：  
当牌山摸完（ryuukyoku / 海底无牌）时，`game.is_ended` 保持为 `False`（`game.py` 未调用 `set_ended()`）。  
`_handle_round_restart()` 的前提条件是 `game.is_ended == True`，导致：
- 双方此时发送 `start_new`，均收到 `round_not_ended` 错误
- 游戏卡死，无法进入下一轮，也无法正常结束

**复现**：  
1. 正常对局打到牌山摸完
2. 流局后双方发送 `start_new`
3. 双方均收到 `{"event": "error", "code": "round_not_ended"}`

**根源**：  
`game.py` 中海底流局的处理路径没有调用 `game.set_ended()` 或将 game status 设置为 ENDED(3)。  
需由游戏逻辑层（game.py）修复，非房间模块职责。

---

## Issue #2：快照中 display_name 显示为 user_id（UUID） ✅ 已修复

**文件**：`server/room/snapshot_manager.py`、`room_manager.py`、`reconnect_manager.py`  
**严重程度**：中（展示问题）  
**状态**：**已修复（2026-04-02）**

**修复内容**：
- `serialize_game()` 新增 `display_names: dict[str, str] | None` 参数
- `RoomManager` 新增 `get_display_names(room_name)` 辅助方法，从 session 中提取真实昵称
- 所有调用 `serialize_game()` 的地方（`room_manager.py` x3、`reconnect_manager.py` x1）统一传入 `display_names`

---

## Issue #3：connect() 中 RECONNECT 失败后可能双重 accept ✅ 已修复

**文件**：`server/room/room_manager.py` — `connect()`  
**严重程度**：低（边界情况）  
**状态**：**已修复（2026-04-02）**

**修复内容**：  
引入 `ws_accepted = False` 标志位，在第一次 `ws.accept()` 后置为 `True`。  
后续所有 accept 调用改为 `if not ws_accepted: await ws.accept()`，防止对同一 WebSocket 重复 accept。

---

## Issue #4：EndDecisionService `all_continue` 需要至少 2 人在线 — 设计行为

**文件**：`server/room/end_decision_service.py` — `choose_continue()`  
**严重程度**：无（设计符合预期）  
**状态**：**不修复（行为正确）**

**结论**：  
代码中 `all_continue = len(online_set) >= 2 and online_set.issubset(continue_set)` 明确要求至少 2 名在线玩家，单人在线时 `all_continue` 始终为 `False`。  
这是 2 人对局的正确逻辑：必须双方同意才能继续。初次分析有误，Issue #4 不是 bug。

---

## Issue #5：Redis 清理中大厅断线玩家的 session key 残留 ✅ 已修复

**文件**：`server/room/room_manager.py` — `_cleanup_redis()`  
**严重程度**：低（Redis 数据残留）  
**状态**：**已修复（2026-04-02）**

**实际问题**：  
初次分析描述了错误的执行顺序（`rooms.pop` 先于 `_cleanup_redis`），实际代码顺序是正确的。  
但存在另一个真实问题：玩家在 WAITING 状态断线时，`_remove_player_from_room()` 将其从 `room.player_ids` 和 `self.sessions` 中移除，导致后续 `cleanup_room()` 无法获取该玩家的 ID 来清除 Redis session key。

**修复内容**：  
`_cleanup_redis()` 中取 `room.player_ids` 与 `self.sessions[room_name].keys()` 的**并集**作为待清除玩家列表，覆盖正常在室和中途离开两种情况。

---

## Issue #6：TimeoutScheduler 异步任务隔离 ✅ 已修复（测试层）

**文件**：`server/room/tests/helpers.py`  
**严重程度**：极低（测试隔离性）  
**状态**：**已修复（2026-04-02，测试辅助层）**

`helpers.py` 中 `run_async()` 改用 `asyncio.new_event_loop()`，每次测试创建独立 event loop 并在结束后关闭，消除跨测试任务泄漏风险。

---

## 修复后测试结果

```
236 passed in 1.49s   （修复前）
```

修复不涉及新增测试路径，重新运行预期 236 passed。
