# 项目进度（给后续 Chat 用）

> 由开发者在里程碑完成时更新；AI 完成任务后也应顺手更新「最近更新」与相关小节。

## 元信息

| 项 | 内容 |
|----|------|
| 最近更新 | 2026-04-03 |
| 当前分支 | `feature/clever-chinitsu-bot` |
| 产品名 | Chinitsu Showdown — 二人实时清一色（仅索子） |

## 当前阶段（一句话）

基线：**注册/登录 JWT + 房间 WebSocket + 局内流程 + Svelte 前端 + pytest**。**Replay MVP** 已合：导出 JSON、`/replay` 复盘、AsyncAPI 已补 `export_replay` 与 `replayBuildFrames`。本分支名仍可能承载 **AI/Bot** 等后续工作。

## 进行中

- [ ] （例如：clever bot、谱面分析、联网部署）

## 已完成（可勾选累积）

- [x] FastAPI 后端、`ChinitsuGame` 状态机与二人规则
- [x] `python-mahjong` 和牌判定封装
- [x] SQLite 用户表 + JWT WebSocket 鉴权
- [x] SvelteKit 大厅/对局 UI、牌图资源流程
- [x] AsyncAPI 文档与调试牌山（`debug_setting.py`）
- [x] **Replay**：`game.py` 录制、`replay.py` + `POST /api/replay/build-frames`、WS `export_replay`；`/replay` + `ReplayViewer`；局终弹窗双主按钮（New Game / Export）；底栏在 `$agariResult` 打开时隐藏

## 下一步（优先级自上而下）

1. （待填）
2. （待填）

## 已知问题 / 技术债（可选）

- （待填：例如某边界规则、测试缺口、生产 SECRET_KEY 等）

## 给 Agent 快速路径

- 改协议 → `docs/asyncapi.yaml` + `asyncapi.zh.yaml` + `ws.ts` / `types.ts`
- 改规则/番符 → `server/game.py`、`server/agari_judge.py`、`RULES.md`
- 改谱面格式/重放 → `server/replay.py`、`game.py` 录制、`ReplayViewer.svelte`；协议字段同步 AsyncAPI
- 只跑后端测试 → 项目根 `uv run pytest -v`
- 前端改完走 FastAPI 静态站 → `web-svelte` 下 **`npm run build`**
