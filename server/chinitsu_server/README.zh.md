# 清一色对决 - 服务端

本仓库包含「清一色对决」的游戏服务端。

## 简介

清一色对决是一款基于麻将清一色规则的双人实时对战游戏，服务端使用 FastAPI + WebSocket 实现。

## 技术栈

- **Python 3** — 运行环境
- **FastAPI + uvicorn** — 异步 Web 服务
- **python-mahjong** — 和牌判定与点数计算
- **WebSocket** — 实时通信

## 快速开始

**启动服务器：**
```bash
python server/start_server.py
```
服务器默认运行在 `127.0.0.1:8000`。

**测试客户端：**

用浏览器打开 `client/index.html`，即可通过以下地址连接到服务器：
```
ws://127.0.0.1:8000/ws/{房间名}/{玩家ID}
```

**下载牌面图片：**
```bash
python scripts/get_images.py
```

## 依赖安装

项目暂无 `requirements.txt`，请手动安装依赖：
```bash
pip install fastapi uvicorn python-mahjong
```

## 项目结构

```
server/
  start_server.py   # 入口：启动 uvicorn
  server.py         # WebSocket 端点与连接管理
  game.py           # 游戏核心逻辑（状态机、回合、动作处理）
  agari_judge.py    # 和牌判定封装
  debug_setting.py  # 调试用预设牌山
client/
  index.html        # 简易测试客户端
scripts/
  get_images.py     # 从 tenhou.net 下载牌面图片
assets/             # 麻将牌 PNG 图片
```

## 游戏状态

| 状态值 | 含义 |
|--------|------|
| 0 | 等待玩家加入 |
| 1 | 对局进行中 |
| 2 | 等待断线玩家重连 |
| 3 | 对局结束 |

## 通信协议

客户端通过 WebSocket 发送 JSON 消息，消息包含 `action` 字段，服务端将游戏状态更新广播给房间内所有玩家。

## 许可证

本项目基于 Apache 2.0 协议开源。
