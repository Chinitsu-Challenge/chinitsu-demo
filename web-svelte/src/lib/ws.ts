import { writable, get } from 'svelte/store';
import type { GameState, AgariData, KawaEntry } from './types';

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
	kyoutaku: 0
});

export const logs = writable<{ text: string; type: string }[]>([]);
export const agariResult = writable<(AgariData & { isMe: boolean }) | null>(null);

// --- Connection state ---
let ws: WebSocket | null = null;
export let myId = '';
export let oppId = '';

export function getMyId() {
	return myId;
}
export function getOppId() {
	return oppId;
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
	playerId: string,
	roomName: string
): Promise<{ ok: boolean; reason?: string }> {
	myId = playerId;

	return new Promise((resolve) => {
		const { protocol, hostname, port } = window.location;
		const wsProto = protocol === 'https:' ? 'wss' : 'ws';
		ws = new WebSocket(`${wsProto}://${hostname}:${port || '8000'}/ws/${roomName}/${myId}`);

		ws.onopen = () => {
			gameState.update((s) => ({ ...s, phase: 'waiting' }));
			logMsg('Connected to room: ' + roomName, 'broadcast');
			resolve({ ok: true });
		};

		ws.onmessage = ({ data }) => {
			handleMessage(JSON.parse(data));
		};

		ws.onclose = (event) => {
			if (event.code === 1003) {
				const reason =
					event.reason === 'room_full'
						? 'Room is full!'
						: event.reason === 'duplicate_id'
							? 'Name already taken in this room.'
							: 'Connection refused.';
				resolve({ ok: false, reason });
			} else {
				logMsg('Disconnected from server.', 'error');
			}
		};

		ws.onerror = () => {
			resolve({ ok: false, reason: 'Connection failed.' });
		};
	});
}

// --- Message handling ---
function handleMessage(data: Record<string, unknown>) {
	if (data.broadcast) {
		logMsg(data.message as string, 'broadcast');
		const msg = data.message as string;
		const joinMatch = msg.match(/^(\S+) joins/);
		const hostMatch = msg.match(/Host is (\S+)/);
		if (joinMatch && joinMatch[1] !== myId) oppId = joinMatch[1];
		if (hostMatch && hostMatch[1] !== myId) oppId = hostMatch[1];
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

		// Update points
		if (data.point && typeof data.point === 'object') {
			const pts = data.point as Record<string, number>;
			for (const [pid, p] of Object.entries(pts)) {
				if (pid === myId) s.myPoints = p;
				else s.oppPoints = p;
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

		return { ...s };
	});
}
