# Dev Log: Spectator Mode

**Date:** 2026-04-13  
**Branch:** `feat/redis_room`  
**Author:** Kenny Lin

---

## Overview

Added a read-only spectator mode to Chinitsu Showdown. Any user who connects to a full room (2 players already present) is automatically admitted as a spectator. Spectators receive an omniscient view of the game (both hands visible) in real time, with no ability to interact.

---

## What Was Added

### New Features

- **Auto-spectator routing** — third+ connections to a room become spectators instead of being rejected.
- **Omniscient view** — spectators see both players' full hands, fuuro, kawa, points, oya/riichi status, wall count, round info, and kyoutaku.
- **Real-time updates** — after every game action the server pushes a `spectator_game_update` broadcast to all spectators in the room.
- **Join snapshot** — on connect the spectator receives an immediate `spectator_snapshot` (if game is running) or a waiting message.
- **Presence events** — `spectator_joined` / `spectator_left` are broadcast to all players and spectators so the entire room stays informed.
- **Capacity limit** — max 10 spectators per room (`MAX_SPECTATORS_PER_ROOM`).
- **One-room restriction** — a user cannot spectate and play simultaneously, and cannot spectate two rooms at once.
- **Action guard** — any WebSocket message from a spectator is rejected with `spectator_action_forbidden` before reaching game logic.
- **Clean teardown** — spectator WebSocket connections are closed when the room expires or is destroyed.

### Frontend UI

- New `SpectatorGame.svelte` component: dark-themed layout showing both player panels side by side, each with name/points/turn indicator, hand tiles, melds, and discards.
- `+page.svelte` routes to `SpectatorGame` when `$isSpectator` is true.
- `ws.ts` stores `isSpectator` (writable boolean) and `spectatorState` (writable `SpectatorState`) and handles all spectator events.

---

## Modified / Added Files

### Backend

| File | Change |
|------|--------|
| `server/room/models.py` | Added `SpectatorSession` dataclass; added `MAX_SPECTATORS_PER_ROOM = 10` |
| `server/room/errors.py` | Added `WS_CLOSE_SPECTATOR_ROOM_FULL` and `ERR_SPECTATOR_ACTION_FORBIDDEN` |
| `server/room/protocol.py` | Added `make_spectator_joined()` and `make_spectator_left()` factories |
| `server/room/snapshot_manager.py` | Added `build_spectator_view()` static method (omniscient, both hands revealed) |
| `server/room/push_service.py` | Refactored to accept `spectators_store`; `broadcast()` now covers spectators too; added `broadcast_spectators()`, `unicast_spectator()`, `get_spectator_count()` |
| `server/room/room_manager.py` | Added `self.spectators` store; all spectator routing in `connect()` / `disconnect()` / `handle_action()`; added `_join_as_spectator()`, `_handle_spectator_disconnect()`, `_push_spectator_update()`, `get_user_spectating_room()`, `_get_spectator()` |
| `server/room/tests/test_spectator.py` | **New** — 25 tests covering join, limit, disconnect, action guard, view correctness, one-room restriction, and cleanup |
| `server/room/tests/test_room_manager.py` | Renamed `test_third_player_rejected_room_full` → `test_third_connection_becomes_spectator`; updated assertions |

### Frontend

| File | Change |
|------|--------|
| `web-svelte/src/lib/types.ts` | Added `SpectatorPlayerData` and `SpectatorState` interfaces |
| `web-svelte/src/lib/ws.ts` | Added `isSpectator` / `spectatorState` stores; `parseSpectatorSnapshot()` helper; handlers for `spectator_snapshot`, `spectator_game_update`, `spectator_joined`, `spectator_left`, `spectator_room_full` |
| `web-svelte/src/lib/components/SpectatorGame.svelte` | **New** — spectator UI component |
| `web-svelte/src/routes/+page.svelte` | Added `{:else if $isSpectator}` branch to render `SpectatorGame` |

### Docs

| File | Change |
|------|--------|
| `docs/asyncapi.yaml` | Added `spectator_room_full` close code; `EvtSpectatorJoined`, `EvtSpectatorLeft`, `EvtSpectatorSnapshot`, `EvtSpectatorGameUpdate` messages and schemas; `spectator_action_forbidden` error code |
| `docs/asyncapi.zh.yaml` | Same additions in Chinese |

---

## Key Design Decisions

### Isolation from player state machine
Spectators are stored in a completely separate `self.spectators: dict[str, dict[str, SpectatorSession]]` store. This means zero changes to the existing reconnect / ready / session state-machine logic. The only shared surface is `PushService.broadcast()`, which now fans out to both stores.

### `broadcast()` semantic includes spectators
Rather than adding a new `broadcast_all()` call everywhere, the existing `broadcast()` was extended to cover spectators automatically. All existing call sites (room lifecycle events, etc.) deliver to spectators without any changes.

### No persistence / no reconnect for spectators
`SpectatorSession` has no Redis serialisation and no reconnect timer. If a spectator disconnects they simply re-join as a new spectator. This keeps the implementation simple and avoids the state-machine complexity that player reconnect required.

### Duplicate-ID check before is_full check
The player duplicate-ID check was moved before the is_full check so a player cannot accidentally enter spectator mode by reconnecting to their own full room.

### AFTER_DISCARD `current_player` convention
`build_spectator_view()` applies the same `current_player` flip as `build_player_view()` in the `after_discard` phase (current player = the one who *can* ron/skip, not the discarder), keeping the frontend convention consistent.

---

## Protocol Summary

### New WS close code
| Code | Reason | Cause |
|------|--------|-------|
| 1003 | `spectator_room_full` | Room already has 10 spectators |

### New broadcast events (players + spectators)
| Event | Payload |
|-------|---------|
| `spectator_joined` | `display_name`, `spectator_count` |
| `spectator_left` | `display_name`, `spectator_count` |

### New spectator-only events (unicast / broadcast to spectators)
| Event | When | Payload |
|-------|------|---------|
| `spectator_snapshot` | On join (game running) | Full omniscient state |
| `spectator_game_update` | After each game action | Full omniscient state |

### New error code
| Code | Cause |
|------|-------|
| `spectator_action_forbidden` | Any action sent by a spectator |

---

## Future Extension Points

The implementation is deliberately minimal but leaves clean hooks for future features:

### 1. Spectator chat / reaction system
`PushService.broadcast_spectators()` and `PushService.unicast_spectator()` are already in place.  
Add a `spectator_chat` action path in `handle_action()` (check `_get_spectator()` first, before the action-forbidden guard) and broadcast a `spectator_message` event.

### 2. Spectator count in game snapshot
`spectatorState.spectatorCount` is already tracked on the frontend via join/leave events.  
To surface it to players, add `spectator_count` to `build_player_view()` output and update `GameState` / `ws.ts`.

### 3. Player reaction to spectator presence
`spectator_joined` / `spectator_left` are already received by players.  
Wire up a UI toast or badge in `Game.svelte` using the existing `logs` store or a separate `spectatorCount` store.

### 4. Spectator reconnect
If reconnect is desired, serialise `SpectatorSession` to Redis with a short TTL (e.g. 30 s) and follow the same snapshot-on-reconnect pattern used for players. `snapshot_manager.build_spectator_view()` is already ready.

### 5. Spectator list endpoint
Add `GET /api/spectators/{room_name}` returning the current spectator roster.  
`room_manager.get_spectator_count()` (via `PushService`) is already callable.

### 6. Mod actions / room owner controls
Add an `ERR_SPECTATOR_KICK_FORBIDDEN` error and a `kick_spectator` action path routed only to the room owner session. `_get_spectator()` can look up the target.
