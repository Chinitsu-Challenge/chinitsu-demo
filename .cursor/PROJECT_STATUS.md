# 项目进度（给后续 Chat 用）

> 由开发者在里程碑完成时更新；AI 完成任务后也应顺手更新「最近更新」与相关小节。

## 元信息

| 项 | 内容 |
|----|------|
| 最近更新 | 2026-04-02 |
| 当前分支 | `feature/clever-chinitsu-bot` |
| 产品名 | Chinitsu Showdown — 二人实时清一色（仅索子） |

## 当前阶段（一句话）

基线已完成：**注册/登录 JWT + 房间 WebSocket + 局内流程（摸切立直杠自摸荣和/流局）+ Svelte 前端 + pytest 集成测试**；本分支名暗示后续可能与「更聪明的 bot / 策略」相关（若尚未实现，见下方「进行中」）。

## 进行中

- [ ] （在此填写当前 sprint / 你正在做的事，例如：clever bot、UI、规则调整）

## 最近合并能力（简记）

- [x] **谱面 / Replay（MVP）**：局内录制 `initial + events`，WS `export_replay` 下载 JSON；`POST /api/replay/build-frames` 生成帧；前端 `/replay` 复盘 + 大厅入口；`Game.svelte` 支持只读 replay 显示模式。

## 已完成（可勾选累积）

- [x] FastAPI 后端、`ChinitsuGame` 状态机与二人规则
- [x] `python-mahjong` 和牌判定封装
- [x] SQLite 用户表 + JWT WebSocket 鉴权
- [x] SvelteKit 大厅/对局 UI、牌图资源流程
- [x] AsyncAPI 文档与调试牌山（`debug_setting.py`）

## 下一步（优先级自上而下）

1. （待填）
2. （待填）

## 已知问题 / 技术债（可选）

- （待填：例如某边界规则、测试缺口、生产 SECRET_KEY 等）

## 给 Agent 的快速路径

- 改协议 → `docs/asyncapi.yaml` + `asyncapi.zh.yaml` + 前后端消息处理
- 改规则/番符 → `server/game.py`、`server/agari_judge.py`、`RULES.md`
- 只跑后端测试 → 项目根 `uv run pytest -v`
