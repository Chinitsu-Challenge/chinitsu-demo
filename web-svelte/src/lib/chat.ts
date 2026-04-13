// chat.ts — emote popup state and EMOTES definition.
// Intentionally has no imports from ws.ts to avoid circular dependencies.
// ws.ts imports from here; components import from both.

import { writable } from 'svelte/store';

export const EMOTES: Record<string, string> = {
	thumbsup: '👍',
	lol: '😂',
	wow: '😮',
	sorry: '🙏',
	skull: '💀',
	gg: 'GG!',
};

export interface EmotePopupData {
	text: string;
	/** true = sent by me (render near bottom), false = sent by opponent (render near top) */
	isMe: boolean;
}

export const emotePopup = writable<EmotePopupData | null>(null);

let _popupTimer: ReturnType<typeof setTimeout> | null = null;

/** Show the emote popup for 2.5 s then clear it. */
export function showEmotePopup(text: string, isMe: boolean): void {
	if (_popupTimer !== null) clearTimeout(_popupTimer);
	emotePopup.set({ text, isMe });
	_popupTimer = setTimeout(() => {
		emotePopup.set(null);
		_popupTimer = null;
	}, 2500);
}
