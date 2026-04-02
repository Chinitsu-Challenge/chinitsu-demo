export interface KawaEntry {
	card: string;
	isRiichi: boolean;
}

export interface GameState {
	phase: 'lobby' | 'waiting' | 'playing' | 'ended' | 'waiting_new_game';
	myHand: string[];
	myIsOya: boolean;
	myPoints: number;
	oppPoints: number;
	myRiichi: boolean;
	oppRiichi: boolean;
	myKawa: KawaEntry[];
	oppKawa: KawaEntry[];
	myFuuro: string[][];
	oppFuuro: string[][];
	currentPlayer: string | null;
	turnStage: 'before_draw' | 'after_draw' | 'after_discard' | null;
	selectedIdx: number | null;
	wallCount: number;
	kyoutaku: number;
	oppDisplayName: string;
}

export interface TenpaiInfo {
	is_tenpai: boolean;
	hand: string[];
}

export interface AgariData {
	agari: boolean;
	action: string;
	player_id: string;
	han?: number;
	fu?: number;
	point: number;
	yaku?: string[];
	hand?: string[];
	tenpai?: Record<string, TenpaiInfo>;
}

/** One scrub step from POST /api/replay/build-frames */
export interface ReplayFrame {
	step: number;
	last_event: { player_id: string; action: string; card_idx: number | null } | null;
	wall_count: number;
	kyoutaku_number: number;
	current_player: string;
	turn_stage: 'before_draw' | 'after_draw' | 'after_discard';
	phase: 'playing' | 'ended';
	hands: Record<string, string[]>;
	kawa: Record<string, [string, boolean][]>;
	fuuro: Record<string, string[][]>;
	balances: Record<string, number>;
	is_oya: Record<string, boolean>;
	riichi: Record<string, boolean>;
	player_ids: string[];
	display_names: Record<string, string>;
	agari?: boolean;
	han?: number;
	fu?: number;
	yaku?: string[];
	ryukyoku?: boolean;
	tenpai?: Record<string, TenpaiInfo>;
	agari_point?: number;
	analysis?: {
		player_id: string;
		kind: 'discard_recommendation';
		summary: string;
		recommendations: Array<{
			card_idx: number;
			discard: string;
			shanten_after: number;
			waits: string[];
			waits_in_wall: number;
		}>;
	};
}
