# 项目进度（给后续 Chat 用）

> 由开发者在里程碑完成时更新；AI 完成任务后也应顺手更新「最近更新」与相关小节。

## 元信息

| 项 | 内容 |
|----|------|
| 最近更新 | 2026-04-17（对局结束 UX 全面修复 + 重连状态恢复） |
| 当前分支 | `feat/create_room` |
| 产品名 | Chinitsu Showdown — 二人实时清一色（仅索子） |

## 当前阶段（一句话）

基线：**注册/登录 JWT + 房间 WebSocket + 局内流程 + Svelte 前端 + pytest**。main 已含 `room/` 模块化架构（RoomManager + 多子服务 + Redis）。**人机对战 v2**：完全模块化，不修改 `game.py`，bot 逻辑独立于 `room/` 架构之外。对局结束 UX 已完善：房主/非房主分流按钮、断线重连后状态完整恢复（含结算界面 + 轮次 AgariOverlay）。

## 进行中

- [ ] 更强 bot（杠、防守、牌效细化）
- [ ] 谱面复盘：切牌建议 / 期望和了
- [ ] CI 监控：前端 `npm run check` 已纳入 CI，需保持 0 errors

## 已完成（可勾选累积）

- [x] FastAPI 后端、`ChinitsuGame` 状态机与二人规则
- [x] `python-mahjong` 和牌判定封装
- [x] SQLite 用户表 + JWT WebSocket 鉴权
- [x] SvelteKit 大厅/对局 UI、牌图资源流程
- [x] AsyncAPI 文档与调试牌山（`debug_setting.py`）
- [x] `room/` 模块化架构：RoomManager、state_machine、PushService、SnapshotManager、TimeoutScheduler、ReadyService、EndDecisionService、ReconnectManager、Redis 集成
- [x] **人机对战 v2（2026-04-13）**：
  - `server/bot_player.py`：纯函数 bot 逻辑（BOT_ID、choose_bot_action），不动 game.py
  - `server/room/bot_service.py`：BotService 异步调度器，接入 RoomManager
  - `server/room/models.py`：Room 加 vs_bot / bot_level 字段
  - `server/room/room_manager.py`：注入 BotService；bot 房间单人即可 start；提取 _post_action_bookkeeping 供 bot chain 复用
  - `server/app.py`：解析 ?bot=1&level=easy|normal|hard 查询参数
  - 前端大厅新增「Play vs CPU」勾选框 + 难度下拉（easy/normal/hard）
- [x] **bot 房间 online_ids 计数 bugfix（2026-04-13）**：
  - 根因：`get_online_user_ids` 只统计有 WebSocket 的 session，bot 无 ws 故永远不计入，导致 bot 房间在线数始终 =1
  - `room_manager.py _handle_game_action`：在线检查改为 `min_online = 1 if room.vs_bot else 2`，修复人类 ron/skip 被 ERR_GAME_PAUSED 静默拒绝的 bug
  - `reconnect_manager.py _handle_running_disconnect`：加 `and not room.vs_bot` 防止人类断线时误判为双方均离线；顺手将 `BOTH_OFFLINE` 改为 `ALL_LEFT`（RUNNING 状态无 BOTH_OFFLINE 转移，是独立 bug）
  - `reconnect_manager.py _handle_reconnect_disconnect`：同上加 bot 房间保护，防止 RECONNECT 状态误销毁
- [x] **对局结束 UX 全面重构（2026-04-17）**：
  - **新 UX 设计**：房主结算框 = 「继续对局」+「解散房间」；非房主 = 「继续对局」+「返回大厅」
  - 「解散房间」：广播 `room_dissolved`，对手看到 10 秒 SVG 圆环倒计时 overlay（`RoomDissolvedOverlay.svelte`），房主自动返回大厅
  - 「返回大厅」（非房主）：`_handle_leave_ended` 静默移除玩家，房间回 WAITING，向房主推送 `player_left_ended`，房主看到右下角 toast 通知（`PlayerLeftNotification.svelte`），10 秒自动消失
  - 新增 `protocol.make_room_dissolved()` / `make_player_left_ended(display_name)`
  - 新增 `isOwner` / `playerLeftNotif` Svelte store；`room_created` 事件写入 `is_owner`
  - **断线重连状态恢复（多个 bug 一次修干净）**：
    - Bug 1 — `isOwner` 重连后丢失：`serialize_game()` 加 `owner_id` 字段；`build_player_view()` 返回 `is_owner`；`game_snapshot` 事件处理时还原 `isOwner` store
    - Bug 2 — 非房主「返回大厅」前端不跳转：`leaveRoom()` 乐观更新 `phase: 'lobby'` 再发送 action
    - Bug 3 — 重入已销毁同名房间显示旧状态：`ws.onopen` 改为 `gameState.set(全量初始值)`，同时重置 `agariResult`、`oppId`、`oppDisplayName` 等所有模块级变量
    - Bug 4 — 轮次结算 AgariOverlay 重连后丢失：
      - `_post_action_bookkeeping()` 加 `last_result` 参数，轮次结束时写 `snapshot["last_round_result"]`
      - `_handle_running_disconnect()` 保留旧快照的 `last_round_result`（防止 serialize_game 覆盖）
      - `on_reconnect()` 及场景 1d 重连后补发 `round_result_restore` 事件
      - `ws.ts` 新增 `round_result_restore` handler，还原 `agariResult`（含 agari/ryukyoku 两种情况）
      - `bot_service.py` 同步传 `last_result` 给 `_post_action_bookkeeping`
  - **CI 修复**：`GameState.phase` 类型联合加入 `'room_dissolved'`，消除 `svelte-check` 3 个 type error

## 下一步（优先级自上而下）

1. 复盘 UI：逐步展示「若切这张」向听/听牌或简单期望（基于谱面 `initial`+已知墙）
2. Bot 杠与更细牌效 / 可选难度
3. 前端 CI `npm run check` 保持 0 errors（已修复 `room_dissolved` type，后续新 phase 值须同步更新 `types.ts`）

## 已知问题 / 技术债（可选）

- 生产环境 SECRET_KEY 需替换为随机值（当前为 dev 默认值）

## 给 Agent 快速路径

- 改协议 → `docs/asyncapi.yaml` + `asyncapi.zh.yaml` + `ws.ts` / `types.ts`（新增 phase 值也要同步 `types.ts`）
- 改规则/番符 → `server/game.py`、`server/agari_judge.py`、`RULES.md`
- 改 bot 逻辑 → `server/bot_player.py`（纯函数，不依赖房间层）
- 改 bot 调度 → `server/room/bot_service.py`
- 只跑后端测试 → 项目根 `uv run pytest -v`
- 前端改完走 FastAPI 静态站 → `web-svelte` 下 **`npm run build`**
