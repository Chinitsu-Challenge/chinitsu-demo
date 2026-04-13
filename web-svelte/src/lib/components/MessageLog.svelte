<script lang="ts">
	import { logs, sendChat } from '$lib/ws';

	let open = $state(false);
	let inputText = $state('');

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

<div id="message-log">
	<div
		class="log-toggle"
		role="button"
		tabindex="0"
		onclick={() => (open = !open)}
		onkeydown={(e) => { if (e.key === 'Enter') open = !open; }}
	>
		Chat {open ? '▼' : '▲'}
	</div>

	<div class="log-content" class:open>
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
</div>

<style>
	#message-log {
		position: fixed;
		bottom: 48px;
		right: 12px;
		width: 260px;
		z-index: 20;
		font-size: 0.78rem;
	}

	.log-toggle {
		cursor: pointer;
		background: rgba(20, 20, 30, 0.85);
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-radius: 0.4rem 0.4rem 0 0;
		padding: 3px 8px;
		user-select: none;
		color: #aaa;
	}

	.log-content {
		display: none;
		flex-direction: column;
		background: rgba(15, 15, 22, 0.92);
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-top: none;
		border-radius: 0 0 0.4rem 0.4rem;
		overflow: hidden;
	}
	.log-content.open {
		display: flex;
	}

	.log-entries {
		max-height: 160px;
		overflow-y: auto;
		padding: 4px 6px;
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
		padding: 4px 6px;
		gap: 4px;
	}

	.chat-input {
		flex: 1;
		background: rgba(255, 255, 255, 0.07);
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-radius: 0.3rem;
		color: #eee;
		font-size: 0.78rem;
		padding: 2px 6px;
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
		padding: 2px 8px;
	}
	.chat-send:hover {
		background: rgba(255, 255, 255, 0.18);
	}
</style>
