# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run server:**
```bash
python server/start_server.py
```
Starts a FastAPI/uvicorn server on `127.0.0.1:8000`.

**Test client:** Open `client/index.html` in a browser and connect to `ws://127.0.0.1:8000/ws/{room}/{player_id}`.

**Download card assets:**
```bash
python scripts/get_images.py
```

**Build frontend (SvelteKit):**
```bash
cd web-svelte && npm install && npm run build
```

**Dev frontend with hot reload:**
```bash
cd web-svelte && npm run dev
```

Vite proxies `/ws` and `/assets` to the FastAPI backend on `:8000`.

`server/test.py` exists but is currently empty.

## Architecture

Chinitsu Showdown is a 2-player real-time mahjong (chinitsu variant) game server.

### Request Flow

```
Client WebSocket → server.py (ConnectionManager) → game.py (ChinitsuGame) → agari_judge.py → python-mahjong lib
```

### Key Files

- **`server/server.py`** — WebSocket endpoint at `/ws/{room_name}/{player_id}`. Manages connections, reconnections, and routes client messages to the game. All game rooms are stored in-memory in `ConnectionManager`.

- **`server/game.py`** — Core game engine. `ChinitsuGame` manages game state (WAITING=0, RUNNING=1, RECONNECT=2, ENDED=3), the wall (yama), turns, and action processing (draw, discard, kan, riichi, tsumo, ron). `ChinitsuPlayer` holds per-player state (hand, points, flags).

- **`server/agari_judge.py`** — Wraps `python-mahjong` to evaluate winning hands, check yaku, and calculate point values.

- **`server/debug_setting.py`** — Provides predetermined card distributions for testing. Activated by debug codes (`114514`, `1001`) passed during game setup.

### Communication Protocol

Clients send JSON messages with an `action` field. The server responds with game state updates broadcast to all players in the room. No authentication; player identity is solely the `player_id` path parameter.

### Dependencies

- `fastapi`, `uvicorn` — server
- `python-mahjong` — hand evaluation
- Dependencies are managed via `uv` — run `uv sync` from the project root

## API Documentation

AsyncAPI specs live at `docs/` in the project root:

| File                    | Purpose                        |
| ----------------------- | ------------------------------ |
| `docs/asyncapi.yaml`    | English spec                   |
| `docs/asyncapi.zh.yaml` | Chinese spec                   |
| `docs/index.html`       | Viewer served at `/api-docs`   |

**When to update the specs:**

Whenever you make any of the following changes, update **both** `asyncapi.yaml` and `asyncapi.zh.yaml`:

- Adding or removing a WebSocket action → update `components/schemas/ActionType/enum`
- Changing a message payload (new field, removed field, type change) → update the relevant schema under `components/schemas/`
- Adding a new message type → add it under `components/messages/` and reference it in the channel's `publish` or `subscribe` oneOf
- Adding an HTTP endpoint → add it as a new channel with the `http` binding
- Changing error codes → update `components/schemas/ErrorCode/enum`

**Validate the spec** (requires Node.js):

```bash
npx @asyncapi/cli validate docs/asyncapi.yaml
npx @asyncapi/cli validate docs/asyncapi.zh.yaml
```

Or paste the YAML into [AsyncAPI Studio](https://studio.asyncapi.com) for a live preview.
