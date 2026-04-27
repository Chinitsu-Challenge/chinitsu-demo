# Chinitsu Showdown - 清一色对战

两人实时麻将对战游戏，专注于**清一色（Chinitsu）**玩法。

---

## 目录

- [快速开始](#快速开始)
- [功能模块](#功能模块)
  - [服务端](#服务端)
  - [前端](#前端)
- [WebSocket 接口](#websocket-接口)
  - [连接地址](#连接地址)
  - [客户端发送消息格式](#客户端发送消息格式)
  - [服务端响应消息格式](#服务端响应消息格式)
  - [Action 详细说明](#action-详细说明)
  - [错误码](#错误码)
- [游戏流程](#游戏流程)
- [配置说明](#配置说明)
- [调试模式](#调试模式)

---

## 快速开始

### 安装 uv（如尚未安装）

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

更多安装方式参见 [uv 官方文档](https://docs.astral.sh/uv/getting-started/installation/)。

### 安装后端依赖

```bash
uv sync
```

此命令会自动创建虚拟环境并安装 `pyproject.toml` 中声明的所有依赖。

### 安装前端依赖

> 需要 Node.js >= 22.12

```bash
cd web-svelte
npm install
```

### 下载牌面素材

```bash
cd server
uv run python scripts/get_images.py
```

从 `tenhou.net` 下载 44 张牌面 PNG 图片到 `assets/` 目录。

### 启动后端服务

```bash
cd server
uv run python start_server.py
```

服务默认运行在 `0.0.0.0:8000`。

### 启动前端开发服务器（可选）

开发时使用，支持热更新：

```bash
cd web-svelte
npm run dev
```

访问 `http://localhost:5173`。生产环境直接访问后端 `http://127.0.0.1:8000/`（需先执行 `npm run build`）。

### 查看 API 文档

服务启动后，浏览器打开 `http://127.0.0.1:8000/api-docs`（默认中文，右上角可切换英文）。

### 开始游戏

1. 浏览器打开 `http://localhost:5173`（开发）或 `http://127.0.0.1:8000/`（生产）
2. 注册账号或登录
3. 输入房间名，按需配置房间设置（仅对创建房间的玩家生效）：
   - **模式**：正常（手牌随机顺序）/ 简单（手牌自动按顺序排列）
   - **起始点数**：50k / 100k / 150k（默认）/ 200k
   - **惩罚点数**：10k / 20k（默认）/ 30k
   - **作弊码**：可选，用于测试特定手牌（见[调试模式](#调试模式)）
4. 点击 Connect 进入房间
5. 两名玩家均进入房间后，点击「开始游戏」

---

## 功能模块

### 服务端

#### `start_server.py` — 服务入口

配置 uvicorn 日志并启动 FastAPI 应用，监听 `0.0.0.0:8000`。

#### `managers.py` — WebSocket 连接管理

| 类 | 职责 |
|---|------|
| `GameManager` | 管理游戏实例的创建、获取和销毁（内存存储） |
| `ConnectionManager` | 管理 WebSocket 连接、消息路由、断线重连 |

核心功能：
- **房间管理**：每个房间最多 2 名玩家，支持房间名 + 玩家 ID 路由
- **连接生命周期**：第一位玩家连接时创建游戏并应用房间设置，第二位连接时可开始游戏
- **断线重连**：玩家断线后游戏进入 `RECONNECT` 状态，重连后恢复游戏
- **静态文件服务**：挂载 `/assets`（牌面图片）和 `/`（前端页面）

#### `game.py` — 核心游戏引擎

**`ChinitsuPlayer` 玩家类**

| 属性 | 类型 | 说明 |
|------|------|------|
| `name` | str | 玩家标识 |
| `point` | int | 当前点数（初始 150,000） |
| `is_oya` | bool | 是否为庄家 |
| `is_riichi` | bool | 是否立直 |
| `is_daburu_riichi` | bool | 是否两立直 |
| `is_ippatsu` | bool | 一发状态 |
| `is_rinshan` | bool | 岭上状态 |
| `is_furiten` | bool | 振听状态 |
| `hand` | list | 手牌列表（如 `["1s", "2s", ...]`） |
| `fuuro` | list | 副露列表（杠的牌组） |
| `kawa` | list | 牌河（弃牌列表） |
| `num_kan` | int | 杠的次数 |

主要方法：

| 方法 | 说明 |
|------|------|
| `draw(cards, is_rinshan)` | 摸牌（普通/岭上） |
| `discard(idx, is_riichi)` | 打出指定位置的牌 |
| `kan(kan_card)` | 杠操作，需有 4 张相同牌 |
| `reset_game()` | 新局重置手牌/副露 |
| `get_info()` | 返回公开的玩家信息 |

**`TurnState` 回合状态**

| 阶段 | 值 | 说明 |
|------|----|------|
| `BEFORE_DRAW` | 1 | 摸牌前 |
| `AFTER_DRAW` | 2 | 摸牌后（可打牌/立直/杠/自摸） |
| `AFTER_DISCARD` | 3 | 打牌后（对手可荣和/跳过） |

**`ChinitsuGame` 游戏类**

| 属性 | 说明 |
|------|------|
| `status` | 游戏状态：WAITING(0) / RUNNING(1) / RECONNECT(2) / ENDED(3) |
| `yama` | 牌山（剩余牌） |
| `kyoutaku_number` | 供托立直棒数 |
| `tsumi_number` | 本场数 |
| `rules` | 规则配置字典 |
| `debug_code` | 调试作弊码（每局自动使用） |

主要方法：

| 方法 | 说明 |
|------|------|
| `add_player(name)` | 注册新玩家 |
| `start_game(oya, debug_code)` | 指定庄家开始游戏 |
| `start_new_game(debug_code)` | 随机庄家开始新局 |
| `draw_from_yama()` | 从牌山摸牌 |
| `draw_from_rinshan()` | 从岭上摸牌（杠后） |
| `input(action, card_idx, player_id)` | 处理玩家操作（核心入口） |

#### `agari_judge.py` — 和牌判定

封装 `python-mahjong` 库的 `HandCalculator`，负责判定手牌是否和牌并计算得分。

**`AgariJudger.judge()` 参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `hand` | list | 手牌 |
| `fuuro` | list | 副露 |
| `win_card` | str | 和牌 |
| `is_tsumo` | bool | 自摸 |
| `is_riichi` | bool | 立直 |
| `is_ippatsu` | bool | 一发 |
| `is_rinshan` | bool | 岭上开花 |
| `is_haitei` | bool | 海底摸月 |
| `is_houtei` | bool | 河底捞鱼 |
| `is_daburu_riichi` | bool | 两立直 |
| `is_tenhou` | bool | 天和 |
| `is_renhou` | bool | 人和 |
| `is_chiihou` | bool | 地和 |
| `is_oya` | bool | 庄家 |
| `kyoutaku_number` | int | 供托数 |
| `tsumi_number` | int | 本场数 |

**返回值** (`HandResponse`)：

| 字段 | 说明 |
|------|------|
| `han` | 翻数 |
| `fu` | 符数 |
| `cost` | 点数支付结构 |
| `yaku` | 达成的役种列表 |

#### `debug_setting.py` — 调试模式

提供预设牌山，用于测试特定手牌场景。

| Debug Code | 庄家初始手牌 | 说明 |
|------------|-------------|------|
| `114514` | 1 1 1 2 3 4 5 5 6 7 8 9 9 9 | 测试场景 1 |
| `1001` | 1 1 1 2 3 4 5 5 5 5 6 7 8 9 | 测试场景 2 |

---

### 前端

前端使用 **SvelteKit**，构建产物由 FastAPI 以静态文件方式提供。

#### `routes/+page.svelte` — 根页面

登录检测 → 自动重连（查询 `/api/active_room`）→ 根据阶段路由：大厅 / 旁观游戏 / 玩家游戏。

#### `lib/components/Lobby.svelte` — 大厅界面

- 用户名显示与登出
- 房间名输入
- 房间设置面板（仅对 Host 生效）：
  - 模式选择：正常 / 简单（自动排牌）
  - 起始点数：50k / 100k / 150k / 200k
  - 惩罚点数：10k / 20k / 30k
  - 作弊码输入（可选）

#### `lib/components/Game.svelte` — 游戏界面

- 对手区域（顶部）：名称、点数、状态徽章
- 对手手牌（背面显示）
- 双方牌河与副露
- 中央信息：牌山剩余、供托、回合指示
- 我方手牌（可点击选择）
- 操作按钮：摸牌、立直、自摸、荣和、跳过、杠、开始游戏
- 消息日志
- 和牌结算浮层

键盘快捷键：

| 按键 | 操作 |
|------|------|
| `D` | 摸牌 |
| `T` | 自摸 |
| `R` | 荣和 |
| `S` | 跳过 |
| `Esc` | 取消选择 |

#### `lib/components/SpectatorGame.svelte` — 旁观界面

全知视角，双方手牌均可见，不可操作。每个房间最多支持 10 名旁观者。

#### `lib/ws.ts` — WebSocket 客户端

管理连接状态、消息路由、Svelte store 更新（`gameState`、`logs`、`agariResult`）。包含重复标签页检测（BroadcastChannel 心跳）。

---

## WebSocket 接口

### 连接地址

```
ws://{host}:{port}/ws/{room_name}?token={jwt_token}[&initial_point=N][&no_agari_punishment=N][&sort_hand=true][&debug_code=N]
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `room_name` | string | 房间标识 |
| `token` | string | 登录后获取的 JWT token |
| `initial_point` | int（可选） | 初始点数，默认 150000（仅 Host 生效） |
| `no_agari_punishment` | int（可选） | 错误和牌罚分，默认 20000（仅 Host 生效） |
| `sort_hand` | bool（可选） | 是否自动排序手牌，默认 false（仅 Host 生效） |
| `debug_code` | int（可选） | 作弊码，启用预设手牌（仅 Host 生效） |

连接前需先通过 `POST /api/register` 或 `POST /api/login` 获取 token。

### 客户端发送消息格式

```json
{
  "action": "string",
  "card_idx": "string"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `action` | string | 操作类型，见下方 Action 说明 |
| `card_idx` | string | 牌的索引（数字字符串）或空字符串 |

### 服务端响应消息格式

**广播消息**（通知所有玩家）：

```json
{
  "broadcast": true,
  "message": "string"
}
```

**游戏状态更新**（发送给特定玩家）：

```json
{
  "broadcast": false,
  "player_id": "string",
  "action": "string",
  "card_idx": 0,
  "card": "5s",
  "hand": ["1s", "2s", "3s", "..."],
  "is_oya": true,
  "message": "ok",
  "current_player": "player1",
  "turn_stage": "after_draw",
  "wall_count": 50,
  "kyoutaku_number": 0,
  "fuuro": {
    "player1": [["1s", "1s", "1s", "1s"]],
    "player2": []
  },
  "kawa": {
    "player1": [["5s", false], ["3s", true]],
    "player2": [["7s", false]]
  },
  "balances": {
    "player1": 150000,
    "player2": 150000
  }
}
```

**和牌结算消息**（额外字段）：

```json
{
  "agari": true,
  "han": 6,
  "fu": 30,
  "point": 12000,
  "yaku": ["Chinitsu", "Riichi"]
}
```

### Action 详细说明

#### `start` / `start_new` — 开始游戏 / 开始新局

- **阶段**：WAITING / ENDED
- **参数**：`card_idx` 可传 debug code（值 > 100 时启用调试模式，会覆盖连接时设置的 `debug_code`）
- **响应**：返回各玩家手牌和庄家信息
- **说明**：分配庄家，洗牌发牌，庄家 14 张，闲家 13 张；若开启 `sort_hand`，发牌后自动排序

#### `draw` — 摸牌

- **阶段**：`BEFORE_DRAW`（当前回合玩家）
- **参数**：无需 `card_idx`
- **响应**：更新后的手牌（若开启 `sort_hand` 则已排序）
- **限制**：庄家第一回合不需摸牌（已有 14 张）；牌山为空时流局

#### `discard` — 打牌

- **阶段**：`AFTER_DRAW`（当前回合玩家）
- **参数**：`card_idx` = 要打出的牌在手牌中的索引（0 起始）
- **响应**：更新后的手牌、牌河
- **限制**：立直状态下只能打最后摸入的牌

#### `riichi` — 立直

- **阶段**：`AFTER_DRAW`（当前回合玩家）
- **参数**：`card_idx` = 要打出的牌的索引
- **响应**：更新后的手牌、牌河、立直状态
- **限制**：未立直时才可声明；第一巡可触发两立直

#### `kan` — 杠

- **阶段**：`AFTER_DRAW`（当前回合玩家）
- **参数**：`card_idx` = 要杠的牌的索引
- **响应**：更新后的手牌、副露，之后自动从岭上摸牌（若开启 `sort_hand` 则已排序）
- **限制**：需手中有 4 张相同牌

#### `tsumo` — 自摸

- **阶段**：`AFTER_DRAW`（当前回合玩家）
- **参数**：无需 `card_idx`
- **响应**：和牌判定结果（`agari`, `han`, `fu`, `point`, `yaku`）
- **说明**：判定失败时扣除罚分

#### `ron` — 荣和

- **阶段**：`AFTER_DISCARD`（非当前回合玩家）
- **参数**：无需 `card_idx`
- **响应**：和牌判定结果
- **说明**：对对手打出的牌声明荣和；判定失败时扣除罚分

#### `skip_ron` — 跳过荣和

- **阶段**：`AFTER_DISCARD`（非当前回合玩家）
- **参数**：无
- **响应**：确认消息
- **说明**：放弃荣和机会，若已立直则支付供托

### 错误码

| 错误消息 | 说明 |
|---------|------|
| `not_your_turn` | 非当前回合玩家尝试操作 |
| `not_opponent_turn` | 在自己回合尝试 ron/skip_ron |
| `card_index_error` | 无效的牌索引格式或超出范围 |
| `illegal_draw` | 非法摸牌（阶段错误或庄家首巡） |
| `illegal_kan` | 非法杠（阶段错误或牌数不足） |
| `illegal_discard` | 非法打牌（阶段错误） |
| `illegal_riichi` | 非法立直（阶段错误或已立直） |
| `illegal_tsumo` | 非法自摸（阶段错误） |
| `illegal_ron` | 非法荣和（阶段错误） |
| `room_full` | 房间已满（2 人） |
| `duplicate_id` | 重复的玩家 ID |
| `not_enough_players` | 玩家不足无法开始 |

**WebSocket 关闭码**：

| 关闭码 | 原因 |
|--------|------|
| `1003` | 连接被拒（`room_full` 或 `duplicate_id`） |
| `1008` | token 无效或已过期，需重新登录 |

---

## 游戏流程

```
注册 / 登录（/api/register 或 /api/login）
    │
    ▼
  大厅（输入房间名，配置房间设置）
    │
    ▼
  等待对手（WAITING）
    │
    ├── 两人到齐 ──▶ 点击「开始游戏」
    │
    ▼
  游戏进行中（RUNNING）
    │
    ▼
  ┌─────────────────────────────┐
  │  回合循环：                  │
  │                             │
  │  BEFORE_DRAW ─── 摸牌       │
  │       │                     │
  │       ▼                     │
  │  AFTER_DRAW ──┬─ 打牌       │
  │               ├─ 立直+打牌  │
  │               ├─ 杠→岭上摸  │
  │               └─ 自摸（和牌）│
  │       │                     │
  │       ▼                     │
  │  AFTER_DISCARD ─┬─ 荣和     │
  │                 └─ 跳过     │
  │       │                     │
  │       ▼                     │
  │  切换到对手 → BEFORE_DRAW   │
  └─────────────────────────────┘
    │
    ▼
  游戏结束（ENDED）
    │
    ├── 开始新局 ──▶ 回到 RUNNING
    └── 断开连接
```

---

## 配置说明

### 游戏规则（`game.py`）

```python
default_rules = {
    "initial_point": 150_000,         # 初始点数
    "no_agari_punishment": 20_000,    # 错误和牌罚分
    "sort_hand": False,               # 是否自动排序手牌（简单模式）
    "yaku_rules": {
        "has_daisharin": False,       # 是否启用大车轮
        "renhou_as_yakuman": False,   # 人和是否作为役满
    }
}
```

上述规则可在 Lobby 界面由 Host 创建房间时配置（`initial_point`、`no_agari_punishment`、`sort_hand`），也可直接通过 WebSocket 连接 query params 传入。

### 服务器地址（`start_server.py`）

```python
uvicorn.run(app, host="0.0.0.0", port=8000)
```

修改 `host` 和 `port` 参数调整监听地址。

---

## 调试模式

### 通过 Lobby 界面

在大厅的「作弊码 Cheat Code」输入框中填入 debug code，Connect 后该局及后续每局均使用预设手牌。

### 通过 WebSocket 动作

在 `start` 或 `start_new` 的 `card_idx` 中传入大于 100 的数值可临时覆盖 debug code：

```json
{"action": "start_new", "card_idx": "114514"}
```

### 支持的 Debug Code

| Code | 庄家手牌（14 张） | 闲家手牌（13 张） |
|------|-----------------|-----------------|
| `114514` | 1 1 1 2 3 4 5 5 6 7 8 9 9 9 | 1 1 1 2 2 2 4 5 6 7 8 9 9 |
| `1001` | 1 1 1 2 3 4 5 5 5 5 6 7 8 9 | 1 2 3 4 5 6 7 8 8 8 8 9 9 |

自定义手牌场景可在 `server/debug_setting.py` 中添加。

---

## 贡献指南

### 修改 API 后请同步更新文档

新增或修改 WebSocket 动作、消息载荷、错误码，或新增 HTTP 接口时，**必须**同步更新以下两个文件：

- `docs/asyncapi.yaml` — 英文规范
- `docs/asyncapi.zh.yaml` — 中文规范

**使用 AI 辅助开发时**，请在提示词中明确告知 AI 需要同步更新文档，例如：

> 修改完代码后，请同步更新 `docs/asyncapi.yaml` 和 `docs/asyncapi.zh.yaml`。
> 如新增动作，在 `components/schemas/ActionType/enum` 中添加；
> 如变更载荷字段，在 `components/schemas/GameStateUpdatePayload` 中更新；
> 如新增错误码，在 `components/schemas/ErrorCode/enum` 中添加。
> 两个文件内容需保持一致，仅语言不同。

详细的字段对应关系见 `server/CLAUDE.md`。
