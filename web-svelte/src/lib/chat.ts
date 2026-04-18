// chat.ts — emote config loader and popup state.
// Loads emotes from JSON config file.

import { writable, get } from 'svelte/store';
import { load as parseYaml } from 'js-yaml';

export interface EmoteDef {
	/** Unique emote ID */
	id: string;
	/** Path to the sticker image (relative to /static) */
	src: string;
	/** Short label shown in the picker tooltip */
	label: string;
}

export interface EmoteSeries {
	/** Series name */
	name: string;
	/** List of emotes in this series */
	emotes: EmoteDef[];
}

export interface EmoteConfig {
	series: EmoteSeries[];
}

// Store for emote config (loaded async)
export const emoteConfig = writable<EmoteConfig | null>(null);

// Flat map for quick lookup by id
export const EMOTES: Record<string, EmoteDef> = {};

// Slash-command map: "suzuran-smile" → "smile", "basic-thumbsup" → "thumbsup"
export const EMOTE_SLUGS: Record<string, string> = {};

// Load emote config from JSON
export async function loadEmoteConfig(): Promise<void> {
	try {
		const res = await fetch('/emotes/emotes.yaml');
		const text = await res.text();
		const config = parseYaml(text) as EmoteConfig;
		emoteConfig.set(config);

		// Rebuild lookup maps
		for (const key of Object.keys(EMOTES)) delete EMOTES[key];
		for (const key of Object.keys(EMOTE_SLUGS)) delete EMOTE_SLUGS[key];
		for (const series of config.series) {
			const prefix = series.name.toLowerCase().replace(/\s+/g, '-');
			for (const emote of series.emotes) {
				EMOTES[emote.id] = emote;
				EMOTE_SLUGS[`${prefix}-${emote.id}`] = emote.id;
			}
		}
	} catch (e) {
		console.error('Failed to load emote config:', e);
	}
}

// Emote popup state — multiple popups can coexist; newer stack on top.
export interface EmotePopupItem {
	id: number;
	emoteId: string;
	isMe: boolean;
}

export const emotePopups = writable<EmotePopupItem[]>([]);

export const EMOTE_POPUP_MS = 3000;

let _emoteSeq = 0;

export function showEmotePopup(emoteId: string, isMe: boolean): void {
	_emoteSeq++;
	const id = _emoteSeq;
	emotePopups.update((arr) => [...arr, { id, emoteId, isMe }]);
	setTimeout(() => {
		emotePopups.update((arr) => arr.filter((p) => p.id !== id));
	}, EMOTE_POPUP_MS);
}

// Chat bubble state
export interface ChatBubbleData {
	text: string;
	isMe: boolean;
	seq: number;
}

export const chatBubble = writable<ChatBubbleData | null>(null);

let _chatTimer: ReturnType<typeof setTimeout> | null = null;
let _chatSeq = 0;

export const CHAT_BUBBLE_MS = 4000;

export function showChatBubble(text: string, isMe: boolean): void {
	if (_chatTimer !== null) clearTimeout(_chatTimer);
	_chatSeq++;
	chatBubble.set({ text, isMe, seq: _chatSeq });
	_chatTimer = setTimeout(() => {
		chatBubble.set(null);
		_chatTimer = null;
	}, CHAT_BUBBLE_MS);
}

/**
 * Measure chat text "width" where CJK / full-width chars count as 2 and
 * ASCII / halfwidth as 1. Used to enforce the 32-char / 16-CJK limit.
 */
export function chatTextWeight(text: string): number {
	let w = 0;
	for (const ch of text) {
		w += ch.charCodeAt(0) > 0x7f ? 2 : 1;
	}
	return w;
}

export const CHAT_MAX_WEIGHT = 32;

/**
 * Truncate text so its weight does not exceed CHAT_MAX_WEIGHT.
 * If truncation actually happens, append "..." (reserving weight 3 for it).
 */
export function truncateChatText(text: string): string {
	if (chatTextWeight(text) <= CHAT_MAX_WEIGHT) return text;
	const budget = CHAT_MAX_WEIGHT - 3;
	let w = 0;
	let out = '';
	for (const ch of text) {
		const cw = ch.charCodeAt(0) > 0x7f ? 2 : 1;
		if (w + cw > budget) break;
		w += cw;
		out += ch;
	}
	return out + '...';
}