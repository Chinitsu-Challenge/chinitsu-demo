# 项目进度（给后续 Chat 用）

> 由开发者在里程碑完成时更新；AI 完成任务后也应顺手更新「最近更新」与相关小节。

## 元信息

| 项 | 内容 |
|----|------|
| 最近更新 | 2026-04-02 |
| 当前分支 | `feature/clever-chinitsu-bot` |
| 产品名 | Chinitsu Showdown — 二人实时清一色（仅索子） |

## 当前阶段（一句话）

基线：**注册/登录 JWT + 房间 WebSocket + 局内流程 + Svelte 前端 + pytest**。**Replay MVP** 已合。**人机对战 MVP**：首位连接带查询参数 `bot=1`（大厅勾选「Play vs CPU」）即入座 CPU，单人即可 `start`；CPU 启发式（向听、立直概率、和了/跳过荣和）。谱面复盘「哪张切牌最优」可后续用枚举+向听/听牌（无需 RL/LLM）。

## 进行中

- [ ] 谱面复盘：切牌建议 / 期望和了（枚举+牌理）
- [ ] 更强 bot（杠、防守、牌效细化）

## 已完成（可勾选累积）

- [x] FastAPI 后端、`ChinitsuGame` 状态机与二人规则
- [x] `python-mahjong` 和牌判定封装
- [x] SQLite 用户表 + JWT WebSocket 鉴权
- [x] SvelteKit 大厅/对局 UI、牌图资源流程
- [x] AsyncAPI 文档与调试牌山（`debug_setting.py`）
- [x] **Replay**：`game.py` 录制、`replay.py` + `POST /api/replay/build-frames`、WS `export_replay`；`/replay` + `ReplayViewer`；局终弹窗双主按钮（New Game / Export）；底栏在 `$agariResult` 打开时隐藏
- [x] **人机**：`GET /ws/{room}?...&bot=1` + `server/bot_player.py`；`managers` 单连接房间锁 + CPU 链式调度；`game.py` vs_bot 双就绪

## 下一步（优先级自上而下）

1. 复盘 UI：逐步展示「若切这张」向听/听牌或简单期望（基于谱面 `initial`+已知墙）
2. Bot 杠与更细牌效 / 可选难度

## 已知问题 / 技术债（可选）

- （待填：例如某边界规则、测试缺口、生产 SECRET_KEY 等）

## 给 Agent 快速路径

- 改协议 → `docs/asyncapi.yaml` + `asyncapi.zh.yaml` + `ws.ts` / `types.ts`
- 改规则/番符 → `server/game.py`、`server/agari_judge.py`、`RULES.md`
- 改谱面格式/重放 → `server/replay.py`、`game.py` 录制、`ReplayViewer.svelte`；协议字段同步 AsyncAPI
- 只跑后端测试 → 项目根 `uv run pytest -v`
- 前端改完走 FastAPI 静态站 → `web-svelte` 下 **`npm run build`**
