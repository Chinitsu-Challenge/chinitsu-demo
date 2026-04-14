<script lang="ts">
	import { logs, sendChat, sendEmote } from '$lib/ws';
	import { EMOTES } from '$lib/chat';

	let open = $state(false);
	let inputText = $state('');
	let showEmotes = $state(false);

	function submit() {
		const text = inputText.trim();
		if (!text) return;
		sendChat(text);
		inputText = '';
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			submit();
		}
		// prevent game hotkeys (d/t/r/s) from firing while typing
		e.stopPropagation();
	}
</script>

<div id="social-panel">
	<div class="social-header">
		<button class="social-tab" class:active={open} onclick={() => { open = !open; showEmotes = false; }}>
			💬 Chat
		</button>
		<button class="social-tab" class:active={showEmotes} onclick={() => { showEmotes = !showEmotes; open = false; }}>
			🃏 Emotes
		</button>
	</div>

	{#if open}
		<div class="social-content">
			<div class="log-entries">
				{#each $logs as entry}
					<div class="log-entry {entry.type}">{entry.text}</div>
				{/each}
			</div>

			<div class="chat-input-row">
				<input
					class="chat-input"
					type="text"
					placeholder="Say something…"
					maxlength="100"
					bind:value={inputText}
					onkeydown={onKeydown}
				/>
				<button class="chat-send" onclick={submit}>Send</button>
			</div>
		</div>
	{/if}

	{#if showEmotes}
		<div class="emote-grid">
			{#each Object.entries(EMOTES) as [id, def]}
				<button class="emote-btn" onclick={() => sendEmote(id)} title={def.label}>
					<img src={def.src} alt={def.label} class="emote-thumb" />
				</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	#social-panel {
		position: fixed;
		bottom: 12px;
		left: 12px;
		z-index: 20;
		font-size: 0.78rem;
	}

	.social-header {
		display: flex;
		gap: 2px;
	}

	.social-tab {
		background: rgba(20, 20, 30, 0.85);
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-bottom: none;
		border-radius: 0.4rem 0.4rem 0 0;
		padding: 6px 12px;
		color: #aaa;
		cursor: pointer;
		font-size: 0.8rem;
		transition: all 0.15s;
	}

	.social-tab:first-child {
		border-radius: 0.4rem 0 0 0;
	}

	.social-tab:last-child {
		border-radius: 0 0.4rem 0 0;
	}

	.social-tab.active {
		background: rgba(30, 30, 45, 0.95);
		color: #fff;
		border-color: rgba(255, 255, 255, 0.25);
	}

	.social-content {
		background: rgba(15, 15, 22, 0.95);
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-radius: 0 0.4rem 0.4rem 0.4rem;
		overflow: hidden;
	}

	.log-entries {
		max-height: 160px;
		overflow-y: auto;
		padding: 6px 8px;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.log-entry {
		color: #bbb;
		word-break: break-word;
		line-height: 1.3;
	}
	.log-entry.broadcast {
		color: #888;
		font-style: italic;
	}
	.log-entry.error {
		color: #e57373;
	}
	.log-entry.chat {
		color: #e0e0e0;
	}
	.log-entry.emote {
		color: #ce93d8;
	}

	.chat-input-row {
		display: flex;
		border-top: 1px solid rgba(255, 255, 255, 0.1);
		padding: 6px 8px;
		gap: 6px;
	}

	.chat-input {
		flex: 1;
		background: rgba(255, 255, 255, 0.07);
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-radius: 0.3rem;
		color: #eee;
		font-size: 0.78rem;
		padding: 4px 8px;
		outline: none;
	}
	.chat-input:focus {
		border-color: rgba(255, 255, 255, 0.35);
	}

	.chat-send {
		background: rgba(255, 255, 255, 0.1);
		border: 1px solid rgba(255, 255, 255, 0.2);
		border-radius: 0.3rem;
		color: #ddd;
		cursor: pointer;
		font-size: 0.75rem;
		padding: 4px 10px;
	}
	.chat-send:hover {
		background: rgba(255, 255, 255, 0.18);
	}

	/* Emote grid */
	.emote-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 6px;
		background: rgba(15, 15, 22, 0.95);
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-top: none;
		border-radius: 0 0.4rem 0.4rem 0.4rem;
		padding: 8px;
	}

	.emote-btn {
		background: none;
		border: 1px solid transparent;
		border-radius: 0.4rem;
		cursor: pointer;
		padding: 4px;
		transition: all 0.1s;
	}

	.emote-btn:hover {
		background: rgba(255, 255, 255, 0.1);
		border-color: rgba(255, 255, 255, 0.2);
		transform: scale(1.05);
	}

	.emote-thumb {
		display: block;
		width: 44px;
		height: 44px;
		border-radius: 0.3rem;
	}
</style>
