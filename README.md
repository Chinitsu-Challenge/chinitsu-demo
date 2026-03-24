# Chinitsu Showdown - 清一色对战

两人实时麻将对战游戏，专注于**清一色（Chinitsu）**玩法，使用 WebSocket 进行实时通信。

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

### 安装依赖

```bash
pip install fastapi uvicorn mahjong
```

### 下载牌面素材

```bash
cd server/chinitsu_server
python scripts/get_images.py
```

从 `tenhou.net` 下载 44 张牌面 PNG 图片到 `assets/` 目录。

### 启动服务

```bash
cd server/chinitsu_server
python server/start_server.py
```

服务默认运行在 `0.0.0.0:8000`。

### 开始游戏

1. 浏览器打开 `http://127.0.0.1:8000/`
2. 输入玩家名和房间名，点击连接
3. 两名玩家进入同一房间后，点击「开始游戏」

---

## 功能模块

### 服务端

#### `start_server.py` — 服务入口

配置 uvicorn 日志并启动 FastAPI 应用，监听 `0.0.0.0:8000`。

#### `server.py` — WebSocket 连接管理

| 类 | 职责 |
|---|------|
| `GameManager` | 管理游戏实例的创建、获取和销毁（内存存储） |
| `ConnectionManager` | 管理 WebSocket 连接、消息路由、断线重连 |

核心功能：
- **房间管理**：每个房间最多 2 名玩家，支持房间名 + 玩家 ID 路由
- **连接生命周期**：第一位玩家连接时创建游戏，第二位连接时可开始游戏
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

| Debug Code | 说明 |
|------------|------|
| `114514` | 预设手牌测试场景 1 |
| `1001` | 预设手牌测试场景 2 |

---

### 前端

#### `index.html` — 游戏界面

- **大厅界面**：输入玩家名和房间名
- **游戏界面**：
  - 对手区域（顶部）：名称、点数、徽章
  - 对手手牌（背面显示）
  - 双方牌河
  - 中央信息：牌山剩余、供托显示、回合指示
  - 我方手牌（可点击选择）
  - 操作按钮：摸牌、立直、自摸、荣和、跳过、杠、开始游戏
  - 消息日志
  - 和牌结算浮层

#### `game.js` — 游戏客户端逻辑

核心游戏状态 (`gameState`)：

| 字段 | 说明 |
|------|------|
| `phase` | 阶段：`lobby` / `waiting` / `playing` / `ended` |
| `myHand` | 我方手牌 |
| `myIsOya` | 我方是否庄家 |
| `myPoints` / `oppPoints` | 双方点数 |
| `myRiichi` / `oppRiichi` | 双方立直状态 |
| `myKawa` / `oppKawa` | 双方牌河 |
| `myFuuro` / `oppFuuro` | 双方副露 |
| `currentPlayer` | 当前回合玩家 |
| `turnStage` | 回合阶段 |
| `wallCount` | 牌山剩余 |
| `kyoutaku` | 供托数 |

键盘快捷键：

| 按键 | 操作 |
|------|------|
| `D` | 摸牌 |
| `T` | 自摸 |
| `R` | 荣和 |
| `S` | 跳过 |
| `Esc` | 取消选择 |

#### `style.css` — 界面样式

主要配色：

| 变量 | 值 | 说明 |
|------|----|------|
| `--felt` | `#1a5c2a` | 麻将桌绿色背景 |
| `--tile-bg` | `#f5f0e1` | 牌面米白色 |
| `--riichi-color` | `#ff4444` | 立直标记红色 |
| `--tsumo-color` | `#44bb44` | 自摸胜利绿色 |

---

## WebSocket 接口

### 连接地址

```
ws://{host}:{port}/ws/{room_name}/{player_id}
```

| 参数 | 类型 | 限制 | 说明 |
|------|------|------|------|
| `room_name` | string | 最长 20 字符 | 房间标识 |
| `player_id` | string | 最长 20 字符 | 玩家标识，同一房间内唯一 |

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
  "hand": ["1s", "2s", "3s", ...],
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
  "point": {
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

#### `start` — 开始游戏

- **阶段**：WAITING
- **参数**：`card_idx` 可传 debug code（值 > 100 时启用调试模式）
- **响应**：返回各玩家手牌和庄家信息
- **说明**：分配庄家，洗牌发牌，庄家 14 张，闲家 13 张

#### `start_new` — 开始新局

- **阶段**：WAITING / ENDED
- **参数**：同 `start`
- **响应**：同 `start`
- **说明**：随机选择庄家，重置游戏状态

#### `draw` — 摸牌

- **阶段**：`BEFORE_DRAW`（当前回合玩家）
- **参数**：无需 `card_idx`
- **响应**：更新后的手牌
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
- **响应**：更新后的手牌、副露，之后自动从岭上摸牌
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

---

## 游戏流程

```
连接 WebSocket
    │
    ▼
  大厅（输入名称/房间）
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
    "sort_hand": False,               # 是否自动排序手牌
    "yaku_rules": {
        "has_daisharin": False,       # 是否启用大车轮
        "renhou_as_yakuman": False,   # 人和是否作为役满
    }
}
```

### 服务器地址（`start_server.py`）

```python
uvicorn.run(app, host="0.0.0.0", port=8000)
```

修改 `host` 和 `port` 参数调整监听地址。

---

## 调试模式

在 `start` 或 `start_new` 的 `card_idx` 中传入大于 100 的数值即可启用调试模式，使用预设牌山代替随机洗牌：

```json
{"action": "start_new", "card_idx": "114514"}
```

支持的 debug code 在 `debug_setting.py` 中定义。
