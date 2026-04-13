import { writable } from 'svelte/store';
import type { GameState, AgariData, KawaEntry, SpectatorState, SpectatorPlayerData } from './types';
import { getToken, getUuid, getUsername } from './auth';

// --- Stores ---
export const gameState = writable<GameState>({
	phase: 'lobby',
	myHand: [],
	myIsOya: false,
	myPoints: 150000,
	oppPoints: 150000,
	myRiichi: false,
	oppRiichi: false,
	myKawa: [],
	oppKawa: [],
	myFuuro: [],
	oppFuuro: [],
	currentPlayer: null,
	turnStage: null,
	selectedIdx: null,
	wallCount: 36,
	kyoutaku: 0,
	oppDisplayName: ''
});

export const logs = writable<{ text: string; type: string }[]>([]);
export const agariResult = writable<(AgariData & { isMe: boolean }) | null>(null);

// --- Spectator state ---
export const isSpectator = writable(false);
export const duplicateTab = writable(false); // true = 另一标签页已占用连接，当前 Tab 正在等待
export const spectatorState = writable<SpectatorState>({
	phase: 'lobby',
	gameStatus: '',
	turnStage: null,
	currentPlayer: null,
	wallCount: 0,
	roundNo: 0,
	roundLimit: 8,
	kyoutaku: 0,
	spectatorCount: 0,
	players: {}
});

// --- Connection state ---
let ws: WebSocket | null = null;
export let myId = '';

// --- Duplicate-tab detection via BroadcastChannel ---
// Active tab (Tab 1): broadcasts a heartbeat every 800 ms while the WS is open.
// Waiting tab (Tab 2): watches for those heartbeats; when they stop for 2 s it
//   knows Tab 1 closed and immediately calls connect() again.
const BC_CHANNEL = 'chinitsu_active_tab';
const HEARTBEAT_INTERVAL_MS = 800;
const HEARTBEAT_TIMEOUT_MS = 2000;

let lastRoomName: string | null = null;
let _txChannel: BroadcastChannel | null = null;
let _txTimer: ReturnType<typeof setInterval> | null = null;
let _rxChannel: BroadcastChannel | null = null;
let _rxTimer: ReturnType<typeof setTimeout> | null = null;

function startSendingHeartbeat(roomName: string) {
	stopSendingHeartbeat();
	if (typeof BroadcastChannel === 'undefined') return;
	_txChannel = new BroadcastChannel(BC_CHANNEL);
	_txTimer = setInterval(() => {
		_txChannel?.postMessage({ type: 'heartbeat', room: roomName });
	}, HEARTBEAT_INTERVAL_MS);
	// Tell waiting tabs immediately when this tab is about to close so they can
	// reconnect before the TCP connection fully drops on the server side.
	window.addEventListener('pagehide', () => {
		_txChannel?.postMessage({ type: 'closing', room: roomName });
	}, { once: true });
}

function stopSendingHeartbeat() {
	if (_txTimer !== null) { clearInterval(_txTimer); _txTimer = null; }
	_txChannel?.close();
	_txChannel = null;
}

function startWatchingHeartbeat() {
	stopWatchingHeartbeat();
	if (typeof BroadcastChannel === 'undefined') {
		// Fallback for browsers without BroadcastChannel (very rare)
		_rxTimer = setTimeout(() => { if (lastRoomName) connect(lastRoomName); }, 5000);
		return;
	}
	_rxChannel = new BroadcastChannel(BC_CHANNEL);
	const arm = () => {
		if (_rxTimer !== null) clearTimeout(_rxTimer);
		_rxTimer = setTimeout(() => {
			// No heartbeat for HEARTBEAT_TIMEOUT_MS → active tab is gone
			stopWatchingHeartbeat();
			if (lastRoomName) connect(lastRoomName);
		}, HEARTBEAT_TIMEOUT_MS);
	};
	_rxChannel.onmessage = (e) => {
		if (e.data?.type === 'heartbeat') {
			arm();
		} else if (e.data?.type === 'closing') {
			// Active tab is explicitly closing — reconnect after a short delay to
			// let the server finish processing its WebSocket disconnect.
			stopWatchingHeartbeat();
			setTimeout(() => { if (lastRoomName) connect(lastRoomName); }, 500);
		}
	};
	arm(); // start the countdown immediately in case heartbeats never arrive
}

function stopWatchingHeartbeat() {
	if (_rxTimer !== null) { clearTimeout(_rxTimer); _rxTimer = null; }
	_rxChannel?.close();
	_rxChannel = null;
}
export let oppId = '';
export let myDisplayName = '';
export let oppDisplayName = '';

export function getMyId() {
	return myId;
}
export function getOppId() {
	return oppId;
}
export function getMyDisplayName() {
	return myDisplayName;
}
export function getOppDisplayName() {
	return oppDisplayName;
}

function logMsg(text: string, type = '') {
	logs.update((l) => [...l, { text, type }]);
}

// --- Actions ---
export function sendAction(action: string, cardIdx?: number | null) {
	if (!ws || ws.readyState !== WebSocket.OPEN) return;
	ws.send(
		JSON.stringify({
			action,
			card_idx: cardIdx != null ? String(cardIdx) : ''
		})
	);
}

// --- Connection ---
export function connect(
	roomName: string,
	options?: { vsBot?: boolean; botLevel?: string }
): Promise<{ ok: boolean; reason?: string }> {
	stopWatchingHeartbeat();
	stopSendingHeartbeat();
	lastRoomName = roomName;
	myId = getUuid();
	myDisplayName = getUsername();
	const token = getToken();
	const { vsBot = false, botLevel = 'normal' } = options ?? {};

	return new Promise((resolve) => {
		let resolved = false;
		const done = (result: { ok: boolean; reason?: string }) => {
			if (!resolved) {
				resolved = true;
				resolve(result);
			}
		};

		// In production, frontend is served by FastAPI on the same origin.
		// In dev, set VITE_WS_URL to point at the backend (e.g. ws://localhost:8000).
		const base = import.meta.env.VITE_WS_URL
			|| `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;
		let url = `${base}/ws/${roomName}?token=${encodeURIComponent(token)}`;
		if (vsBot) url += `&bot=1&level=${encodeURIComponent(botLevel)}`;
		console.log('[ws] connecting to', url);
		ws = new WebSocket(url);

		const timeout = setTimeout(() => {
			console.log('[ws] connection timed out');
			ws?.close();
			done({ ok: false, reason: 'Connection timed out.' });
		}, 5000);

		ws.onopen = () => {
			clearTimeout(timeout);
			console.log('[ws] connected');
			stopWatchingHeartbeat();
			startSendingHeartbeat(roomName);
			duplicateTab.set(false);
			// Reset spectator state on every new connection
			isSpectator.set(false);
			spectatorState.update((s) => ({ ...s, phase: 'lobby', players: {} }));
			gameState.update((s) => ({ ...s, phase: 'waiting' }));
			logMsg('Connected to room: ' + roomName, 'broadcast');
			done({ ok: true });
		};

		ws.onmessage = ({ data }) => {
			handleMessage(JSON.parse(data));
		};

		ws.onclose = (event) => {
			clearTimeout(timeout);
			if (event.code === 1008) {
				done({ ok: false, reason: 'Authentication failed. Please login again.' });
			} else if (event.code === 1003) {
				if (event.reason === 'duplicate_id') {
					duplicateTab.set(true);
					startWatchingHeartbeat();
					done({ ok: false, reason: 'duplicate_id' });
					return;
				}
				const reason =
					event.reason === 'room_full'
						? 'Room is full!'
						: event.reason === 'spectator_room_full'
							? 'Spectator seats are full (max 10).'
							: event.reason === 'already_in_room'
								? 'You are already in another room.'
								: 'Connection refused.';
				done({ ok: false, reason });
			} else {
				stopSendingHeartbeat();
				done({ ok: false, reason: 'Disconnected from server.' });
			}
		};

		ws.onerror = () => {
			clearTimeout(timeout);
			stopSendingHeartbeat();
			done({ ok: false, reason: 'Connection failed.' });
		};
	});
}

// --- Message handling ---
function handleBroadcastEvent(data: Record<string, unknown>) {
	const event = data.event as string;

	if (event === 'player_joined') {
		const dn = data.display_name as string;
		logMsg(`${dn} joined the room`, 'broadcast');
		if (dn && dn !== myDisplayName) {
			oppDisplayName = dn;
			gameState.update((s) => ({ ...s, oppDisplayName: dn }));
		}
		return;
	}

	if (event === 'player_left') {
		logMsg(`${data.display_name as string} left the room`, 'broadcast');
		return;
	}

	if (event === 'start_ready_changed') {
		const readyIds = data.ready_user_ids as string[];
		if (readyIds.includes(myId)) {
			gameState.update((s) => ({ ...s, phase: 'waiting_new_game' }));
		}
		return;
	}

	if (event === 'continue_vote_changed') {
		const continueIds = data.continue_user_ids as string[];
		if (continueIds.includes(myId)) {
			gameState.update((s) => ({ ...s, phase: 'waiting_new_game' }));
		}
		return;
	}

	if (event === 'match_restarted') {
		gameState.update((s) => ({ ...s, phase: 'waiting' }));
		logMsg('Match restarted. Click Start to begin!', 'broadcast');
		return;
	}

	if (event === 'match_ended') {
		const reason = data.reason as string;
		const scores = data.final_scores as Record<string, number>;
		const myScore = scores[myId] ?? 0;
		const oppScore = scores[oppId] ?? 0;
		logMsg(
			`Match over (${reason}). Final — You: ${myScore.toLocaleString()}, Opp: ${oppScore.toLocaleString()}`,
			'broadcast'
		);
		gameState.update((s) => ({ ...s, phase: 'ended' }));
		return;
	}

	if (event === 'reconnect_timeout') {
		const winnerId = data.winner_id as string;
		const isWinner = winnerId === myId;
		logMsg(
			isWinner ? 'Opponent timed out. You win!' : 'Reconnect timed out. You lose.',
			'broadcast'
		);
		gameState.update((s) => ({ ...s, phase: 'ended' }));
		return;
	}

	if (event === 'room_expired' || event === 'room_closed') {
		logMsg('Room closed.', 'broadcast');
		gameState.update((s) => ({ ...s, phase: 'lobby' }));
		isSpectator.set(false);
		return;
	}

	if (event === 'spectator_joined') {
		const count = data.spectator_count as number;
		spectatorState.update((s) => ({ ...s, spectatorCount: count }));
		logMsg(`${data.display_name as string} is now watching (${count} watching)`, 'broadcast');
		return;
	}

	if (event === 'spectator_left') {
		const count = data.spectator_count as number;
		spectatorState.update((s) => ({ ...s, spectatorCount: count }));
		logMsg(`${data.display_name as string} stopped watching (${count} watching)`, 'broadcast');
		return;
	}

	// Legacy: old-format broadcast with a plain message string
	const msg = data.message as string | undefined;
	if (msg) {
		logMsg(msg, 'broadcast');
		const joinMatch = msg.match(/^(.+) joins/);
		const hostMatch = msg.match(/Host is ([^.]+)/);
		if (joinMatch && joinMatch[1] !== myDisplayName) {
			oppDisplayName = joinMatch[1];
			gameState.update((s) => ({ ...s, oppDisplayName: joinMatch[1] }));
		}
		if (hostMatch && hostMatch[1] !== myDisplayName) {
			oppDisplayName = hostMatch[1];
			gameState.update((s) => ({ ...s, oppDisplayName: hostMatch[1] }));
		}
	}
}

function parseSpectatorSnapshot(data: Record<string, unknown>): SpectatorState {
	const raw = (data.players ?? {}) as Record<string, Record<string, unknown>>;
	const players: Record<string, SpectatorPlayerData> = {};
	for (const [pid, pd] of Object.entries(raw)) {
		players[pid] = {
			display_name: pd.display_name as string,
			hand: (pd.hand as string[]) ?? [],
			fuuro: (pd.fuuro as string[][]) ?? [],
			kawa: ((pd.kawa as [string, boolean][]) ?? []).map(([card, isRiichi]) => ({ card, isRiichi })),
			point: (pd.point as number) ?? 0,
			is_oya: (pd.is_oya as boolean) ?? false,
			is_riichi: (pd.is_riichi as boolean) ?? false,
			num_kan: (pd.num_kan as number) ?? 0
		};
	}
	const gameStatus = (data.game_status as string) ?? '';
	const phase: SpectatorState['phase'] = gameStatus === 'ended' ? 'watching_ended' : 'watching';
	return {
		phase,
		gameStatus,
		turnStage: (data.turn_stage as SpectatorState['turnStage']) ?? null,
		currentPlayer: (data.current_player as string) || null,
		wallCount: (data.wall_count as number) ?? 0,
		roundNo: (data.round_no as number) ?? 0,
		roundLimit: (data.round_limit as number) ?? 8,
		kyoutaku: (data.kyoutaku_number as number) ?? 0,
		spectatorCount: 0, // maintained separately by spectator_joined/left events
		players
	};
}

function handleMessage(data: Record<string, unknown>) {
	// 0. Spectator snapshots — this client is a spectator
	if (data.event === 'spectator_snapshot' || data.event === 'spectator_game_update') {
		isSpectator.set(true);
		spectatorState.set(parseSpectatorSnapshot(data));
		// Also sync spectatorCount from the current store value (preserved across updates)
		return;
	}

	// 1. Reconnect snapshot — restore full game state
	if (data.event === 'game_snapshot') {
		const me = data.me as Record<string, unknown>;
		const opp = data.opponent as Record<string, unknown>;
		if (data.opponent_id) oppId = data.opponent_id as string;
		const newOppDisplayName = (opp.display_name as string) || '';
		if (newOppDisplayName) oppDisplayName = newOppDisplayName;
		gameState.update((s) => {
			const stage = data.turn_stage as string;
			const validStages = ['before_draw', 'after_draw', 'after_discard'];
			// Use game_status to restore the correct phase:
			//   "ended"   → phase 'ended'   (round over, show New Game button)
			//   otherwise → phase 'playing'
			const gameStatus = data.game_status as string;
			const restoredPhase: GameState['phase'] =
				gameStatus === 'ended' ? 'ended' : 'playing';
			return {
				...s,
				phase: restoredPhase,
				myHand: me.hand as string[],
				myFuuro: me.fuuro as string[][],
				myKawa: (me.kawa as [string, boolean][]).map(([card, isRiichi]) => ({ card, isRiichi })),
				myPoints: me.point as number,
				myIsOya: me.is_oya as boolean,
				myRiichi: me.is_riichi as boolean,
				oppFuuro: opp.fuuro as string[][],
				oppKawa: (opp.kawa as [string, boolean][]).map(([card, isRiichi]) => ({ card, isRiichi })),
				oppPoints: opp.point as number,
				oppRiichi: opp.is_riichi as boolean,
				oppDisplayName: newOppDisplayName || s.oppDisplayName,
				turnStage: (validStages.includes(stage) ? stage : s.turnStage) as typeof s.turnStage,
				currentPlayer: data.current_player as string,
				wallCount: data.wall_count as number,
				kyoutaku: data.kyoutaku_number as number,
				selectedIdx: null,
			};
		});
		return;
	}

	// 2. Broadcast events (room/match lifecycle)
	if (data.broadcast) {
		handleBroadcastEvent(data);
		return;
	}

	// 3. Non-broadcast protocol events (unicast, no action field)
	if (data.event === 'opponent_disconnected') {
		logMsg('Opponent disconnected. Waiting for reconnect...', 'broadcast');
		return;
	}

	if (data.event === 'opponent_reconnected') {
		logMsg('Opponent reconnected!', 'broadcast');
		return;
	}

	// 4. Legacy: waiting_for_opponent message (old protocol compatibility)
	if (data.message === 'waiting_for_opponent') {
		gameState.update((s) => ({ ...s, phase: 'waiting_new_game' }));
		return;
	}

	const action = data.action as string;
	const actorId = data.player_id as string;

	gameState.update((s) => {
		// Update kawa
		if (data.kawa) {
			for (const [pid, kawa] of Object.entries(data.kawa as Record<string, [string, boolean][]>)) {
				const parsed: KawaEntry[] = (kawa as [string, boolean][]).map(([card, isRiichi]) => ({
					card,
					isRiichi
				}));
				if (pid === myId) s.myKawa = parsed;
				else {
					s.oppKawa = parsed;
					oppId = pid;
				}
			}
		}

		// Update fuuro
		if (data.fuuro) {
			for (const [pid, fuuro] of Object.entries(data.fuuro as Record<string, string[][]>)) {
				if (pid === myId) s.myFuuro = fuuro;
				else {
					s.oppFuuro = fuuro;
					oppId = pid;
				}
			}
		}

		if (data.hand) s.myHand = data.hand as string[];
		if (data.is_oya !== undefined) s.myIsOya = data.is_oya as boolean;

		// Update point balances
		if (data.balances && typeof data.balances === 'object') {
			const pts = data.balances as Record<string, number>;
			for (const [pid, p] of Object.entries(pts)) {
				if (pid === myId) s.myPoints = p;
				else {
					s.oppPoints = p;
					oppId = pid;
				}
			}
		}

		// Update kyoutaku
		if (data.kyoutaku_number !== undefined) s.kyoutaku = data.kyoutaku_number as number;

		// Error messages
		if (data.message && data.message !== 'ok') {
			logMsg(`[${action}] ${data.message}`, 'error');
		}

		// Process actions
		if (action === 'start' || action === 'start_new') {
			s.phase = 'playing';
			s.myRiichi = false;
			s.oppRiichi = false;
			s.selectedIdx = null;
			s.wallCount = 36 - 27;
			if (s.myIsOya) {
				s.currentPlayer = myId;
				s.turnStage = 'after_draw';
			} else {
				s.currentPlayer = oppId;
				s.turnStage = 'after_draw';
			}
			logMsg('Game started!', 'broadcast');
		}

		if (action === 'draw') {
			s.turnStage = 'after_draw';
			s.currentPlayer = actorId;
			s.wallCount--;
			s.selectedIdx = null;
		}

		if (action === 'discard') {
			s.selectedIdx = null;
			s.turnStage = 'after_discard';
			s.currentPlayer = actorId === myId ? oppId : myId;
		}

		if (action === 'riichi') {
			s.selectedIdx = null;
			if (actorId === myId) {
				s.myRiichi = true;
				s.turnStage = 'after_discard';
				s.currentPlayer = oppId;
			} else {
				s.oppRiichi = true;
				s.turnStage = 'after_discard';
				s.currentPlayer = myId;
			}
		}

		if (action === 'kan') {
			s.turnStage = 'after_draw';
			s.currentPlayer = actorId;
			s.wallCount--;
			s.selectedIdx = null;
		}

		if (action === 'skip_ron') {
			s.currentPlayer = actorId;
			s.turnStage = 'before_draw';
		}

		// Agari result
		if (data.agari !== undefined) {
			s.phase = 'ended';
			const isMe = actorId === myId;
			agariResult.set({
				agari: data.agari as boolean,
				action: action,
				player_id: actorId,
				han: data.han as number | undefined,
				fu: data.fu as number | undefined,
				point: data.point as number,
				yaku: data.yaku as string[] | undefined,
				hand: data.hand as string[] | undefined,
				isMe
			});
		}

		// Ryukyoku (exhaustive draw)
		if (data.ryukyoku) {
			s.phase = 'ended';
			agariResult.set({
				agari: false,
				action: 'ryukyoku',
				player_id: actorId,
				point: 0,
				tenpai: data.tenpai as Record<string, { is_tenpai: boolean; hand: string[] }>,
				isMe: false
			});
		}

		return { ...s };
	});
}
