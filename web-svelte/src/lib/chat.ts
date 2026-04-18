// chat.ts — emote config loader and popup state.
// Loads emotes from JSON config file.

import { writable, get } from 'svelte/store';

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

// Legacy: flat map for quick lookup by id
export const EMOTES: Record<string, EmoteDef> = {};

// Load emote config from JSON
export async function loadEmoteConfig(): Promise<void> {
	try {
		const res = await fetch('/emotes/emotes.json');
		const config: EmoteConfig = await res.json();
		emoteConfig.set(config);

		// Build flat lookup map
		EMOTES.clear();
		for (const series of config.series) {
			for (const emote of series.emotes) {
				EMOTES[emote.id] = emote;
			}
		}
	} catch (e) {
		console.error('Failed to load emote config:', e);
	}
}

// Popup state
export interface EmotePopupData {
	emoteId: string;
	isMe: boolean;
}

export const emotePopup = writable<EmotePopupData | null>(null);

let _popupTimer: ReturnType<typeof setTimeout> | null = null;

export function showEmotePopup(emoteId: string, isMe: boolean): void {
	if (_popupTimer !== null) clearTimeout(_popupTimer);
	emotePopup.set({ emoteId, isMe });
	_popupTimer = setTimeout(() => {
		emotePopup.set(null);
		_popupTimer = null;
	}, 2500);
}