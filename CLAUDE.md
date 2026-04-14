# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Install Python dependencies (from project root):**
```bash
uv sync
```

**Start the backend server:**
```bash
cd server
uv run python start_server.py
```
Listens on `0.0.0.0:8000`. API docs at `http://127.0.0.1:8000/api-docs`.

**Download tile image assets (required once before running):**
```bash
cd server
uv run python scripts/get_images.py
```

**Frontend dev server (with hot reload, proxies to backend):**
```bash
cd web-svelte
npm install
npm run dev
```

**Frontend production build:**
```bash
cd web-svelte
npm run build
```

**Frontend type checking:**
```bash
cd web-svelte
npm run check
```

**Validate AsyncAPI specs:**
```bash
npx @asyncapi/cli validate docs/asyncapi.yaml
npx @asyncapi/cli validate docs/asyncapi.zh.yaml
```

**Run tests:**
```bash
uv run pytest -v                    # All tests (from project root)
uv run pytest tests/test_server.py  # Legacy integration tests
uv run pytest server/room/tests/    # Room module unit tests
```

After any frontend change, run `npm run build` from `web-svelte/` before testing through FastAPI.

## Architecture

Chinitsu Showdown is a 2-player real-time mahjong game (chinitsu/清一色 variant — bamboo tiles only). The backend is a Python FastAPI app; the frontend is SvelteKit. They communicate via WebSocket (game) and HTTP REST (auth).

### Tech Stack

- **Backend**: Python 3.12+, FastAPI, WebSockets, Redis (optional, memory fallback), aiosqlite
- **Frontend**: SvelteKit, TypeScript, Svelte 5
- **Game Logic**: `mahjong` library for hand evaluation
- **Auth**: JWT (HS256, 24-hour expiry), bcrypt password hashing

### Request Flow

```
Browser (SvelteKit)
  ├── HTTP POST ──▶ /api/register, /api/login        (auth.py + database.py)
  ├── HTTP GET  ──▶ /api/active_room                  (app.py → RoomManager)
  └── WebSocket ──▶ /ws/{room_name}?token={jwt}       (app.py → ConnectionManager)
                          │
                          ▼
                    RoomManager (room/room_manager.py)
                     ├── Room state machine (room/state_machine.py)
                     ├── ReconnectManager, PushService, SnapshotManager
                     ├── ReadyService, EndDecisionService, MatchEndEvaluator
                     └── TimeoutScheduler
                          │
                          ▼
                    ChinitsuGame (game.py) ──▶ AgariJudger (agari_judge.py) ──▶ python-mahjong
```

### Backend (`server/`)

#### Core Application

- **`app.py`** — FastAPI app entry point. Routes: `POST /api/register`, `POST /api/login`, `GET /api/active_room`, `WS /ws/{room_name}?token={jwt}`. Static file mounts for `/assets`, `/api-docs`, `/`. CORS middleware enabled.
- **`auth.py`** — JWT token creation/verification, bcrypt password hashing, user registration and login.
- **`database.py`** — aiosqlite wrapper. Users table: `(uuid, username, password_hash, created_at)`.
- **`redis_client.py`** — Async Redis connection for room/session persistence (optional; in-memory fallback if unavailable).
- **`managers.py`** — Thin adapter: `ConnectionManager` delegates to `RoomManager` for connect/disconnect/game_action.
- **`start_server.py`** — Configures uvicorn logging and starts the app.

#### Game Logic

- **`game.py`** — Core game engine. `ChinitsuGame` manages turn state (`BEFORE_DRAW=1`, `AFTER_DRAW=2`, `AFTER_DISCARD=3`). `ChinitsuPlayer` holds hand, kawa (discards), fuuro (melds), and flags (riichi, ippatsu, furiten, etc.). The `input(action, card_idx, player_id)` method is the single entry point for all player actions.
- **`agari_judge.py`** — Wraps `python-mahjong`'s `HandCalculator` to validate winning hands and compute han/fu/points. Also provides `get_tenpai_tiles()` for exhaustive draw (ryukyoku) resolution.
- **`debug_setting.py`** — Predetermined tile distributions for testing. Activated by passing a debug code (`114514`, `1001`, etc.) as `card_idx` in a `start`/`start_new` action (value must be > 100).

#### Room Management Module (`server/room/`)

This module handles room lifecycle, player sessions, spectators, and all coordination above the game logic layer.

- **`room_manager.py`** — Central coordinator. Manages rooms, player sessions, spectator sessions, and game instances. Handles connection routing (reconnect vs. join vs. spectate), action dispatch by room state, and room lifecycle (creation → destruction).
- **`state_machine.py`** — Pure-function room state machine. See "Room State Machine" section below.
- **`models.py`** — Data models: `Room`, `PlayerSession`, `SpectatorSession`, `RoomStatus` enum, `RoomEvent` enum. Key constants: `ROOM_MAX_LIFETIME_SEC=2400`, `RECONNECT_TIMEOUT_SEC=120`, `DEFAULT_ROUND_LIMIT=8`, `MAX_SPECTATORS_PER_ROOM=10`.
- **`reconnect_manager.py`** — Handles player disconnect (mark offline, start timer, notify opponent) and reconnect (restore session, cancel timer, push snapshot).
- **`push_service.py`** — WebSocket broadcasting: unicast, broadcast (players + spectators), and connection management.
- **`snapshot_manager.py`** — Serializes game state for reconnection and spectator views. `build_player_view()` hides opponent's hand; `build_spectator_view()` is omniscient. Stores in Redis or in-memory fallback.
- **`ready_service.py`** — Double-confirmation before game start (both players must ready up).
- **`end_decision_service.py`** — Continue/end voting after match ends.
- **`match_end_evaluator.py`** — Determines if match should end: `round_no >= round_limit` or any player's `point < 0`.
- **`timeout_scheduler.py`** — Async timer management for room expiry (40 min), reconnect grace (120 sec), and future action timeouts.
- **`protocol.py`** — Message format factories for all WebSocket payloads (room events, reconnect events, spectator events, errors).
- **`errors.py`** — Error codes (WebSocket close codes like 1008/1003, in-game JSON error codes) and exception classes.

### Room State Machine

```
WAITING ──BOTH_READY──▶ RUNNING ──PLAYER_DISCONNECT──▶ RECONNECT
   │                      │  ▲                            │  │
   │                      │  └──PLAYER_RECONNECT──────────┘  │
   │                      │                                   │
   │                 MATCH_END                        RECONNECT_TIMEOUT
   │                      │                                   │
   │                      ▼                                   │
   │                    ENDED ◀───────────────────────────────┘
   │                      │
   │               BOTH_CONTINUE
   │                      │
   └◀─────────────────────┘

Any state ──ALL_LEFT / ROOM_EXPIRED──▶ DESTROYED
ENDED ──ANY_END_GAME──▶ DESTROYED
RECONNECT ──BOTH_OFFLINE──▶ DESTROYED
```

### Connection Scenarios (priority order)

When a player connects to `/ws/{room_name}`, `RoomManager.connect()` checks:

1. **Reconnect (RECONNECT state)**: Offline player reconnecting → restore session, resume game
2. **Relink (ENDED state)**: Offline player returning after match ended → restore session
3. **Rapid relink (RUNNING)**: Race condition window reconnect → restore session
4. **One-room enforcement**: Reject if player already in a different active room
5. **Duplicate ID**: Reject if same user_id already online in this room (WebSocket close 1003)
6. **Spectator**: Room full (2 players) → join as spectator (max 10)
7. **Create room**: First player → create WAITING room
8. **Join room**: Second player → join existing WAITING room

### Game Turn Flow

```
BEFORE_DRAW ──draw──▶ AFTER_DRAW ──discard/riichi──▶ AFTER_DISCARD
     ▲                      │                              │
     │                    kan ──▶ (rinshan draw) ──┐       │
     │                    tsumo ──▶ (round ends)   │       │
     │                                             │       │
     └─────────────────────────────────────────────┘       │
     └──(opponent's turn, swap current_player)◀────────────┘
                                                    ron ──▶ (round ends)
                                                    skip_ron ──▶ (continue, set furiten)
```

**All player actions**: `start`, `start_new`, `cancel_start`, `draw`, `discard`, `riichi`, `kan`, `tsumo`, `ron`, `skip_ron`, `continue_game`, `end_game`, `leave_room`

### Frontend (`web-svelte/src/`)

- **`lib/ws.ts`** — WebSocket client + Svelte stores (`gameState`, `logs`, `agariResult`, `isSpectator`, `duplicateTab`, `spectatorState`). Handles connection, message routing, and action sending. Includes **duplicate tab detection** via BroadcastChannel API (heartbeat every 800ms; waiting tab auto-reconnects after 2s silence).
- **`lib/types.ts`** — TypeScript interfaces: `GameState` (phase, hand, kawa, fuuro, points, turn info), `SpectatorState`, `AgariData`, `KawaEntry`.
- **`routes/+page.svelte`** — Root page. Login check → auto-reconnect (fetches `/api/active_room`) → phase routing: lobby / spectator game / player game. Shows duplicate-tab warning overlay when needed.
- **`lib/components/`**:
  - **`Login.svelte`** — Username/password with register/login toggle, JWT storage
  - **`Lobby.svelte`** — Room name input, connect button, login status
  - **`Game.svelte`** — Main playing UI: opponent hand (hidden), both kawas, center info panel, player hand (selectable). Keyboard shortcuts: `d`=draw, `t`=tsumo, `r`=ron, `s`=skip_ron, `Esc`=deselect
  - **`SpectatorGame.svelte`** — Omniscient view: both players' hands visible, all game state shown
  - **`Hand.svelte` / `OpponentHand.svelte`** — Player's selectable hand / opponent's tile-count display
  - **`Kawa.svelte`** — Discard pile with riichi markers (rotated tiles)
  - **`Fuuro.svelte`** — Meld display (kan groups)
  - **`Tile.svelte`** — Single tile image renderer with rotation prop
  - **`AgariOverlay.svelte`** — Modal for win/penalty/ryukyoku results
  - **`MessageLog.svelte`** — Color-coded event log

Vite proxies `/ws` → `ws://localhost:8000` and `/assets` → `http://localhost:8000` during development.

### Tile Rotation

Tile images are pre-rendered at four rotations. The `rotation` prop on `<Tile>` selects the correct asset — **never use CSS `transform: rotate()` to orient tiles**.

| `rotation` | Asset suffix | Dimensions | Use |
| --- | --- | --- | --- |
| `0` | `_0.png` | 63 × 95 (portrait) | Normal upright tile |
| `1` | `_1.png` | 85 × 78 (landscape) | Riichi discard (player side) |
| `2` | `_2.png` | 63 × 95 (portrait) | Opponent-side face-up tiles (kawa, fuuro) |
| `3` | `_3.png` | 85 × 78 (landscape) | Riichi discard (opponent side) |

Back tiles (`back_*.png`) follow the same numbering but rotation 0 is used for both sides — the back design is orientation-neutral.

### WebSocket Protocol

**Client → Server:**
```json
{"action": "string", "card_idx": "string"}
```

**Server → Client (three message categories):**

1. **Broadcast** (`"broadcast": true`): Room events sent to all players + spectators
   - Events: `player_joined`, `player_left`, `start_ready_changed`, `continue_vote_changed`, `match_ended`, `room_expired`, `spectator_joined`, `spectator_left`, `reconnect_timeout`, `match_restarted`

2. **Unicast protocol** (`"broadcast": false, "event": "..."`): Per-player events
   - Events: `game_snapshot` (reconnect state restore), `spectator_snapshot` (spectator view), `opponent_disconnected`, `opponent_reconnected`, `error`

3. **Action response** (`"broadcast": false`): Game action results
   - Fields: `action`, `message`, `hand`, `fuuro`, `kawa`, `balances`, `kyoutaku_number`, `current_player`, `turn_stage`, `wall_count`
   - Win fields: `agari`, `han`, `fu`, `point`, `yaku`
   - Ryukyoku fields: `ryukyoku`, `tenpai`

### Key Design Patterns

- **Multi-round matches**: Each round is a fresh `ChinitsuGame` instance. Match tracks `round_no` / `round_limit` (default 8). After each round, players vote continue or end.
- **Reconnection**: 120-second grace period. Session preserved in memory + Redis. Opponent notified. On timeout, disconnected player forfeits.
- **Spectator mode**: Up to 10 spectators per room. Omniscient view (both hands visible). Cannot take actions.
- **Duplicate tab detection**: BroadcastChannel heartbeat prevents two tabs from connecting simultaneously. Second tab waits and auto-reconnects when first closes.
- **Furiten**: Permanent (riichi + skipped ron) and temporary (non-riichi skipped ron, cleared on next discard). Checked before ron is allowed.
- **Race condition protection**: Each connection gets a unique `connection_id`; stale disconnect events from old connections are ignored.

### Default Game Rules (`game.py`)

```python
default_rules = {
    "initial_point": 150_000,
    "no_agari_punishment": 20_000,
    "sort_hand": False,
    "yaku_rules": {
        "has_daisharin": False,
        "renhou_as_yakuman": False,
    }
}
```

## API Documentation

AsyncAPI specs live in `docs/`:

| File | Purpose |
|---|---|
| `docs/asyncapi.yaml` | English spec |
| `docs/asyncapi.zh.yaml` | Chinese spec |
| `docs/index.html` | Viewer served at `/api-docs` |

**Whenever you change the WebSocket protocol, update both spec files:**
- New/removed action → `components/schemas/ActionType/enum`
- Changed message payload → `components/schemas/GameStateUpdatePayload`
- New message type → `components/messages/` + channel `oneOf`
- New HTTP endpoint → new channel with `http` binding
- Changed error codes → `components/schemas/ErrorCode/enum`

Both files must stay in sync (same structure, different language only).
