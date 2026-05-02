export interface KawaEntry {
	card: string;
	isRiichi: boolean;
}

export interface MatchResult {
	reason: 'round_limit_reached' | 'point_zero' | string;
	winnerId: string | null;
	finalScores: Record<string, number>;
}

export interface GameState {
	phase: 'lobby' | 'waiting' | 'playing' | 'ended' | 'waiting_new_game' | 'room_dissolved';
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
	roundNo: number;
	roundLimit: number;
	oppDisplayName: string;
	matchResult: MatchResult | null;
}

export interface SpectatorPlayerData {
	display_name: string;
	hand: string[];
	fuuro: string[][];
	kawa: KawaEntry[];
	point: number;
	is_oya: boolean;
	is_riichi: boolean;
	num_kan: number;
}

export interface SpectatorState {
	phase: 'watching' | 'watching_ended' | 'lobby';
	gameStatus: string;
	turnStage: 'before_draw' | 'after_draw' | 'after_discard' | null;
	currentPlayer: string | null;
	wallCount: number;
	roundNo: number;
	roundLimit: number;
	kyoutaku: number;
	spectatorCount: number;
	players: Record<string, SpectatorPlayerData>;
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
	reason?: string;
}
