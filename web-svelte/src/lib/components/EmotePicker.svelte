<script lang="ts">
	import { EMOTES } from '$lib/chat';
	import { sendEmote } from '$lib/ws';

	let open = $state(false);
</script>

<div class="emote-picker">
	<button
		class="emote-toggle"
		onclick={() => (open = !open)}
		title="Send emote"
		aria-label="Emote picker"
	>😄</button>

	{#if open}
		<div class="emote-tray">
			{#each Object.entries(EMOTES) as [id, glyph]}
				<button
					class="emote-btn"
					onclick={() => { sendEmote(id); open = false; }}
					title={id}
				>{glyph}</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	.emote-picker {
		position: relative;
		display: inline-flex;
		align-items: center;
	}

	.emote-toggle {
		background: none;
		border: 1px solid rgba(255, 255, 255, 0.25);
		border-radius: 0.4rem;
		color: inherit;
		cursor: pointer;
		font-size: 1.2rem;
		padding: 0.2rem 0.45rem;
		line-height: 1;
		transition: background 0.15s;
	}
	.emote-toggle:hover {
		background: rgba(255, 255, 255, 0.1);
	}

	.emote-tray {
		position: absolute;
		bottom: calc(100% + 6px);
		left: 0;
		display: flex;
		gap: 4px;
		background: rgba(20, 20, 30, 0.95);
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-radius: 0.6rem;
		padding: 6px;
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
		z-index: 30;
		white-space: nowrap;
	}

	.emote-btn {
		background: none;
		border: 1px solid transparent;
		border-radius: 0.4rem;
		color: inherit;
		cursor: pointer;
		font-size: 1.4rem;
		padding: 0.2rem 0.3rem;
		line-height: 1;
		transition: background 0.1s, border-color 0.1s;
	}
	.emote-btn:hover {
		background: rgba(255, 255, 255, 0.12);
		border-color: rgba(255, 255, 255, 0.25);
	}
</style>
