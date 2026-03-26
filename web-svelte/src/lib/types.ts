export interface KawaEntry {
	card: string;
	isRiichi: boolean;
}

export interface GameState {
	phase: 'lobby' | 'waiting' | 'playing' | 'ended';
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
