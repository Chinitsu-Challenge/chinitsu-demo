# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run server:**
```bash
python start_server.py
```
Starts a FastAPI/uvicorn server on `0.0.0.0:8000` (all interfaces).

> **VSCode note:** VSCode Helper binds `localhost:8000` and intercepts browser connections even with `remote.autoForwardPorts: false`. Always access via the machine's LAN IP (e.g. `http://10.110.11.x:8000`), not `localhost`.

**Test client:** Open `client/index.html` in a browser and connect to `ws://<LAN-IP>:8000/ws/{room}/{player_id}`.

**Download card assets:**
```bash
python scripts/get_images.py
```

**Build frontend (SvelteKit):**
```bash
cd ../web-svelte && npm install && npm run build
```

**Dev frontend with hot reload:**
```bash
cd ../web-svelte && npm run dev
```

For hot-reload dev, set `VITE_WS_URL=ws://<LAN-IP>:8000` in `web-svelte/.env.local` so the dev server connects directly to the backend. Do **not** rely on Vite's WebSocket proxy — it is unreliable for this use case.

**Normal workflow (no hot reload needed):** build with `npm run build`, then serve everything through FastAPI at port 8000. `VITE_WS_URL` should be left unset so `ws.ts` derives the WebSocket URL from `window.location.host` at runtime — no IP hardcoding required.

## Architecture

Chinitsu Showdown is a 2-player real-time mahjong (chinitsu variant) game server.

### Request Flow

```
Client WebSocket → app.py (routes) + managers.py (ConnectionManager) → game.py (ChinitsuGame) → agari_judge.py → python-mahjong lib
```

### Key Files

- **`app.py`** — FastAPI app, HTTP auth routes (`/api/register`, `/api/login`), WebSocket endpoint at `/ws/{room_name}`, static file mounts.

- **`managers.py`** — `GameManager` owns in-memory game rooms; `ConnectionManager` routes messages and handles disconnect/reconnect.

- **`game.py`** — Core game engine. `ChinitsuGame` manages game state (WAITING=0, RUNNING=1, RECONNECT=2, ENDED=3), the wall (yama), turns, and action processing (draw, discard, kan, riichi, tsumo, ron). `ChinitsuPlayer` holds per-player state (hand, points, flags).

- **`agari_judge.py`** — Wraps `python-mahjong` to evaluate winning hands, check yaku, and calculate point values.

- **`debug_setting.py`** — Provides predetermined card distributions for testing. Activated by debug codes (`114514`, `1001`) passed during game setup.

### Communication Protocol

Clients send JSON messages with an `action` field. The server responds with game state updates broadcast to all players in the room. Player identity comes from JWT tokens passed as a query parameter on the WebSocket URL.

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
