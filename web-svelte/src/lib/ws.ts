import { writable, get } from 'svelte/store';
import type { GameState, AgariData, KawaEntry, SpectatorState, SpectatorPlayerData } from './types';
import { getToken, getUuid, getUsername } from './auth';
import { EMOTES, showEmotePopup, showChatBubble } from './chat';

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
	oppDisplayName: '',
	matchResult: null
});

export const logs = writable<{ text: string; type: string }[]>([]);
export const agariResult = writable<(AgariData & { isMe: boolean }) | null>(null);

// --- Room ownership ---
export const isOwner = writable(false);

// --- Player-left notification (shown to host when non-host leaves in ENDED) ---
export const playerLeftNotif = writable<{ displayName: string } | null>(null);

// --- Connection error overlay (post-connection unexpected WS close / watchdog) ---
export const wsError = writable<{ message: string } | null>(null);

// --- In-game error toast (ERR_* server messages) ---
export const errorToast = writable<{ message: string; id: number } | null>(null);

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

// --- Watchdog: detect silent hangs during gameplay ---
// If no WS message arrives for WATCHDOG_MS while in 'playing' phase,
// the connection is likely dead (TCP keepalive didn't catch it). Show the error overlay.
const WATCHDOG_MS = 60_000;
let _watchdogTimer: ReturnType<typeof setTimeout> | null = null;
// Suppress watchdog while we know the opponent is reconnecting (up to 120s server timeout).
let _opponentDisconnected = false;

function resetWatchdog() {
	if (_watchdogTimer !== null) clearTimeout(_watchdogTimer);
	_watchdogTimer = setTimeout(() => {
		if (get(gameState).phase === 'playing' && !_opponentDisconnected) {
			wsError.set({ message: '长时间未收到服务器消息，连接可能已中断。\n请返回大厅重新连接。' });
		}
	}, WATCHDOG_MS);
}

function stopWatchdog() {
	if (_watchdogTimer !== null) { clearTimeout(_watchdogTimer); _watchdogTimer = null; }
}

// --- WS close reason → user-friendly message ---
function mapCloseReason(code: number, reason: string): string {
	if (reason === 'room_expired')       return '房间已过期（超过 40 分钟未活动）。';
	if (reason === 'room_closed')        return '房间已被关闭。';
	if (reason === 'invalid_room_name')  return '房间不存在或名称非法。';
	if (reason === 'already_in_room')    return '你已在其他房间中，请刷新页面。';
	if (code === 1001)                   return '服务器已关闭该房间。';
	if (code === 1008)                   return '登录已过期，请重新登录后再试。';
	if (code === 1006)                   return '网络连接意外中断。';
	return '与服务器的连接已断开，请返回大厅重新连接。';
}

// --- ERR_* server code → user-friendly message ---
function mapErrorCode(code: string, detail?: string): string {
	const msgs: Record<string, string> = {
		game_paused:               '对手正在重连，操作已暂停',
		game_not_started:          '游戏尚未开始',
		game_ended:                '当前轮已结束',
		not_enough_players:        '需要对手加入才能开始',
		round_not_ended:           '当前轮尚未结束',
		unknown_action:            '无效操作',
		game_error:                `游戏发生错误${detail ? '：' + detail : '，请重试'}`,
		spectator_action_forbidden:'旁观者无法进行游戏操作',
	};
	return msgs[code] ?? `操作被拒绝：${code}`;
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

export function sendChat(text: string) {
	if (!ws || ws.readyState !== WebSocket.OPEN) return;
	ws.send(JSON.stringify({ action: 'chat', text }));
}

export function sendEmote(emoteId: string) {
	if (!ws || ws.readyState !== WebSocket.OPEN) return;
	ws.send(JSON.stringify({ action: 'emote', emote_id: emoteId }));
}

// --- Connection ---
export interface RoomSettings {
	initialPoint?: number;
	noAgariPunishment?: number;
	debugCode?: number;
	sortHand?: boolean;
	vsBot?: boolean;
	botLevel?: string;
}

export function connect(
	roomName: string,
	settings?: RoomSettings
): Promise<{ ok: boolean; reason?: string }> {
	stopWatchingHeartbeat();
	stopSendingHeartbeat();
	lastRoomName = roomName;
	myId = getUuid();
	myDisplayName = getUsername();
	const token = getToken();

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
		const params = new URLSearchParams({ token });
		if (settings?.initialPoint != null)        params.set('initial_point', String(settings.initialPoint));
		if (settings?.noAgariPunishment != null)   params.set('no_agari_punishment', String(settings.noAgariPunishment));
		if (settings?.debugCode != null)           params.set('debug_code', String(settings.debugCode));
		if (settings?.sortHand != null)            params.set('sort_hand', String(settings.sortHand));
		if (settings?.vsBot)                       params.set('bot', '1');
		if (settings?.botLevel)                    params.set('level', settings.botLevel);
		const url = `${base}/ws/${roomName}?${params}`;
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
			// Full reset — clears all stale game state from previous sessions.
			// game_snapshot / player_joined will restore the correct values if reconnecting.
			wsError.set(null);
			_opponentDisconnected = false;
			resetWatchdog();
			isSpectator.set(false);
			isOwner.set(false);
			playerLeftNotif.set(null);
			agariResult.set(null);
			oppId = '';
			oppDisplayName = '';
			gameState.set({
				phase: 'waiting',
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
				oppDisplayName: '',
				matchResult: null,
			});
			spectatorState.update((s) => ({ ...s, phase: 'lobby', players: {} }));
			logMsg('Connected to room: ' + roomName, 'broadcast');
			done({ ok: true });
		};

		ws.onmessage = ({ data }) => {
			resetWatchdog(); // any message from server resets the silence timer
			handleMessage(JSON.parse(data));
		};

		ws.onclose = (event) => {
			clearTimeout(timeout);
			stopWatchdog();
			stopSendingHeartbeat();

			const phase = get(gameState).phase;

			// ── 初次连接阶段（Promise 未 resolve）─────────────────────────────
			// done() 内部有 resolved 保护，多次调用安全
			if (!resolved) {
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
						event.reason === 'room_full'         ? 'Room is full!'
						: event.reason === 'spectator_room_full' ? 'Spectator seats are full (max 10).'
						: event.reason === 'already_in_room'     ? 'You are already in another room.'
						: 'Connection refused.';
					done({ ok: false, reason });
				} else {
					done({ ok: false, reason: 'Connection failed.' });
				}
				return;
			}

			// ── 游戏进行中断连（Promise 已 resolve）─────────────────────────
			// 以下两种 phase 已有专属 UI 处理，不显示通用错误 overlay
			if (phase === 'lobby')          return; // room_closed / leave_room 事件已导航
			if (phase === 'room_dissolved') return; // RoomDissolvedOverlay 负责倒计时

			// 其他所有情况：玩家在游戏中意外断连，显示连接错误 overlay
			wsError.set({ message: mapCloseReason(event.code, event.reason) });
		};

		ws.onerror = () => {
			clearTimeout(timeout);
			stopWatchdog();
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
		gameState.update((s) => ({ ...s, phase: 'waiting', matchResult: null }));
		agariResult.set(null);
		logMsg('Match restarted. Click Start to begin!', 'broadcast');
		return;
	}

	if (event === 'match_ended') {
		const reason = data.reason as string;
		const scores = data.final_scores as Record<string, number>;
		const winnerId = (data.winner_id as string | null) ?? null;
		gameState.update((s) => ({
			...s,
			phase: 'ended',
			matchResult: { reason, winnerId, finalScores: scores },
		}));
		return;
	}

	if (event === 'reconnect_timeout') {
		_opponentDisconnected = false; // reconnect window has closed
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

	if (event === 'room_dissolved') {
		// 房主解散了房间，非房主看到 10 秒倒计时提示框
		gameState.update((s) => ({ ...s, phase: 'room_dissolved' }));
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

	if (event === 'chat') {
		const dn = data.display_name as string;
		const text = data.text as string;
		const isMe = dn === myDisplayName;
		logMsg(`${isMe ? 'You' : dn}: ${text}`, 'chat');
		showChatBubble(text, isMe);
		return;
	}

	if (event === 'emote') {
		const dn = data.display_name as string;
		const emoteId = data.emote_id as string;
		const isMe = dn === myDisplayName;
		showEmotePopup(emoteId, isMe);
		const label = EMOTES[emoteId]?.label ?? emoteId;
		logMsg(`${isMe ? 'You' : dn}: [${label}]`, 'emote');
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
		// Restore owner status (server derives it from snapshot.owner_id)
		if (data.is_owner !== undefined) isOwner.set(data.is_owner as boolean);
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
	if (data.event === 'room_created') {
		// 记录当前用户是否为房主（仅创建者收到此消息，且 is_owner: true）
		if (data.is_owner) isOwner.set(true);
		return;
	}

	if (data.event === 'opponent_disconnected') {
		_opponentDisconnected = true; // suppress watchdog during 120s reconnect window
		logMsg('Opponent disconnected. Waiting for reconnect...', 'broadcast');
		return;
	}

	if (data.event === 'opponent_reconnected') {
		_opponentDisconnected = false;
		logMsg('Opponent reconnected!', 'broadcast');
		return;
	}

	if (data.event === 'error') {
		const code = data.code as string;
		const detail = data.detail as string | undefined;
		errorToast.set({ message: mapErrorCode(code, detail), id: Date.now() });
		// Still log for debug visibility
		logMsg(`[error] ${code}${detail ? ': ' + detail : ''}`, 'error');
		return;
	}

	if (data.event === 'player_left_ended') {
		// 非房主玩家在 ENDED 状态离开，通知房主
		const displayName = data.display_name as string;
		// 切换到 waiting 状态（房间已回到 WAITING，等待新玩家加入）
		agariResult.set(null);
		gameState.update((s) => ({ ...s, phase: 'waiting', matchResult: null }));
		// 展示小型提示框（自动 10 秒消失）
		playerLeftNotif.set({ displayName });
		return;
	}

	if (data.event === 'round_result_restore') {
		// 重连后恢复轮次结算画面（round ended but match not yet over）
		const action = data.action as string;
		const actorId = data.player_id as string;
		gameState.update((s) => ({ ...s, phase: 'ended' }));
		if (data.agari !== undefined) {
			const isMe = actorId === myId;
			agariResult.set({
				agari: data.agari as boolean,
				action,
				player_id: actorId,
				han: data.han as number | undefined,
				fu: data.fu as number | undefined,
				point: data.point as number,
				yaku: data.yaku as string[] | undefined,
				hand: (data.winner_hand as string[] | undefined) ?? (data.hand as string[] | undefined),
				reason: data.error as string | undefined,
				isMe
			});
		} else if (data.ryukyoku) {
			agariResult.set({
				agari: false,
				action: 'ryukyoku',
				player_id: actorId,
				point: 0,
				tenpai: data.tenpai as Record<string, { is_tenpai: boolean; hand: string[] }>,
				isMe: false
			});
		}
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
			console.log('[DEBUG] Agari result:', data);
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
				hand: (data.winner_hand as string[] | undefined) ?? (data.hand as string[] | undefined),
				reason: data.error as string | undefined,
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
