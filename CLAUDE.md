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

Tests are in `tests/test_server.py`. Run with `uv run pytest -v` from the project root. Manual testing uses a browser connected to `ws://127.0.0.1:8000/ws/{room_name}?token={jwt}`, or the debug codes described below.

## Architecture

Chinitsu Showdown is a 2-player real-time mahjong game (chinitsu/清一色 variant — bamboo tiles only). The backend is a Python FastAPI app; the frontend is SvelteKit. They communicate exclusively via WebSocket.

### Request Flow

```
Browser (SvelteKit) ──WebSocket──▶ app.py (routes) + managers.py (ConnectionManager/GameManager)
                                        │
                                        ▼
                                   game.py (ChinitsuGame / ChinitsuPlayer)
                                        │
                                        ▼
                                   agari_judge.py ──▶ python-mahjong lib
```

### Backend (`server/`)

- **`app.py`** — FastAPI app, HTTP auth, `POST /api/replay/build-frames`, WebSocket at `/ws/{room_name}`, static mounts (`/assets`, `/api-docs`, `/`).
- **`managers.py`** — `GameManager` owns in-memory game rooms; `ConnectionManager` routes messages and handles disconnect/reconnect (game enters `RECONNECT` state when a player drops).
- **`game.py`** — Core engine. `ChinitsuGame` tracks game state (`WAITING=0`, `RUNNING=1`, `RECONNECT=2`, `ENDED=3`) and turn state (`BEFORE_DRAW=1`, `AFTER_DRAW=2`, `AFTER_DISCARD=3`). `ChinitsuPlayer` holds hand, kawa, fuuro, riichi/ippatsu/furiten flags. The `input(action, card_idx, player_id)` method is the single entry point for all player actions.
- **`agari_judge.py`** — Wraps `python-mahjong`'s `HandCalculator` to validate winning hands and compute han/fu/points.
- **`debug_setting.py`** — Predetermined tile distributions for testing. Activated by passing a debug code (`114514`, `1001`) as `card_idx` in a `start`/`start_new` action (value must be > 100).
- **`start_server.py`** — Configures uvicorn logging and starts the app.

### Frontend (`web-svelte/src/`)

- **`lib/ws.ts`** — WebSocket client wrapper; all server communication goes through here.
- **`lib/types.ts`** — Shared TypeScript types for game state.
- **`routes/+page.svelte`** — Single page that switches between lobby and game views.
- **`lib/components/`** — `Game`, `Lobby`, `ReplayViewer`, `Hand`, `OpponentHand`, `Kawa`, `Fuuro`, `Tile`, `AgariOverlay`, `MessageLog`; route `routes/replay/+page.svelte` for offline scrubber.

Vite proxies `/ws` → `ws://localhost:8000` and `/assets` → `http://localhost:8000` during development.

### Tile rotation

Tile images are pre-rendered at four rotations. The `rotation` prop on `<Tile>` selects the correct asset — **never use CSS `transform: rotate()` to orient tiles**.

| `rotation` | Asset suffix | Dimensions | Use |
| --- | --- | --- | --- |
| `0` | `_0.png` | 63 × 95 (portrait) | Normal upright tile |
| `1` | `_1.png` | 85 × 78 (landscape) | Riichi discard (player side) |
| `2` | `_2.png` | 63 × 95 (portrait) | Opponent-side face-up tiles (kawa, fuuro) |
| `3` | `_3.png` | 85 × 78 (landscape) | Riichi discard (opponent side) |

Back tiles (`back_*.png`) follow the same numbering but rotation 0 is used for both sides — the back design is orientation-neutral.

After any frontend change, run `npm run build` from `web-svelte/` before testing through FastAPI.

### Replay (谱面)

- **`server/replay.py`** — `build_frames(replay_json)` re-simulates a saved round from `initial` + `events` for the scrub UI.
- **`server/replay_recorder.py`** — Room-scoped replay recorder service (initial snapshot/events/display_names), currently in-memory and easy to swap for Redis-backed storage.
- **`server/replay_codec.py`** — Optional `compact_v1` encoding for smaller replay JSON (`export_replay` with `card_idx: compact`).
- **`server/game.py`** — Core deterministic state machine; provides `snapshot_for_replay()` but does not own replay persistence/export.
- **HTTP:** `POST /api/replay/build-frames` — body = full replay JSON → `{ "frames": [...] }`.
- **WebSocket:** `export_replay` — empty `card_idx` returns full replay; `card_idx: compact` (or `c`) returns `encoding: compact_v1`. Client downloads JSON; `/replay` accepts either shape via `POST /api/replay/build-frames`.
- **Frontend:** `routes/replay/+page.svelte`, `lib/components/ReplayViewer.svelte`, `lib/replayView.ts`; lobby links to `/replay`. Round-end controls (**New Game**, **Export replay**) live in `AgariOverlay`; the action bar stays hidden while `$agariResult` is set.

### WebSocket Protocol

Client sends: `{"action": "string", "card_idx": "string"}`

Actions: `start`, `start_new`, `draw`, `discard`, `riichi`, `kan`, `tsumo`, `ron`, `skip_ron`, `export_replay`

Server responds per-player with full game state (hand, kawa, fuuro, points, turn info). Winning responses include `agari`, `han`, `fu`, `point`, `yaku` fields. `export_replay` success adds a `replay` object.

Authentication: JWT via `?token=` on the WebSocket URL (see `/api/register`, `/api/login`). Room capacity is 2 players; connecting to a full room closes with code `1003`.

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
