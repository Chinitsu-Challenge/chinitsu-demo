// chat.ts — emote popup state and EMOTES definition.
// Intentionally has no imports from ws.ts to avoid circular dependencies.
// ws.ts imports from here; components import from both.

import { writable } from 'svelte/store';

export interface EmoteDef {
	/** Path to the sticker image (relative to /static) */
	src: string;
	/** Short label shown in the picker tooltip */
	label: string;
}

export const EMOTES: Record<string, EmoteDef> = {
	thumbsup: { src: '/emotes/thumbsup.svg', label: 'nice!' },
	lol:      { src: '/emotes/lol.png',      label: 'lol'   },
	wow:      { src: '/emotes/wow.svg',       label: 'wow'   },
	sorry:    { src: '/emotes/sorry.png',     label: 'sorry' },
	skull:    { src: '/emotes/skull.svg',     label: 'rip'   },
	gg:       { src: '/emotes/gg.png',        label: 'GG'    },
};

export interface EmotePopupData {
	/** Emote ID, used to look up the image src */
	emoteId: string;
	/** true = sent by me (render near bottom), false = sent by opponent (render near top) */
	isMe: boolean;
}

export const emotePopup = writable<EmotePopupData | null>(null);

let _popupTimer: ReturnType<typeof setTimeout> | null = null;

/** Show the emote popup for 2.5 s then clear it. */
export function showEmotePopup(emoteId: string, isMe: boolean): void {
	if (_popupTimer !== null) clearTimeout(_popupTimer);
	emotePopup.set({ emoteId, isMe });
	_popupTimer = setTimeout(() => {
		emotePopup.set(null);
		_popupTimer = null;
	}, 2500);
}
