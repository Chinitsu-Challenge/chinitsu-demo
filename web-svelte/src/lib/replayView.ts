import type { GameState, KawaEntry, ReplayFrame } from './types';

export function frameToGameState(frame: ReplayFrame, povMyId: string): GameState {
	const oppId = frame.player_ids.find((id) => id !== povMyId) ?? '';
	const dn = frame.display_names || {};
	const toKawa = (rows: [string, boolean][] | undefined): KawaEntry[] =>
		(rows ?? []).map(([card, isRiichi]) => ({ card, isRiichi }));

	return {
		phase: frame.phase === 'ended' ? 'ended' : 'playing',
		myHand: frame.hands[povMyId] ?? [],
		myIsOya: Boolean(frame.is_oya[povMyId]),
		myPoints: frame.balances[povMyId] ?? 150000,
		oppPoints: frame.balances[oppId] ?? 150000,
		myRiichi: Boolean(frame.riichi[povMyId]),
		oppRiichi: Boolean(frame.riichi[oppId]),
		myKawa: toKawa(frame.kawa[povMyId]),
		oppKawa: toKawa(frame.kawa[oppId]),
		myFuuro: frame.fuuro[povMyId] ?? [],
		oppFuuro: frame.fuuro[oppId] ?? [],
		currentPlayer: frame.current_player,
		turnStage: frame.turn_stage,
		selectedIdx: null,
		wallCount: frame.wall_count,
		kyoutaku: frame.kyoutaku_number,
		oppDisplayName: dn[oppId] || oppId.slice(0, 8)
	};
}
