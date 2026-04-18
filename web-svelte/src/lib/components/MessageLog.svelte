<script lang="ts">
	import { logs, sendChat, sendEmote } from '$lib/ws';
	import {
		emoteConfig,
		loadEmoteConfig,
		EMOTE_SLUGS,
		chatTextWeight,
		truncateChatText,
		CHAT_MAX_WEIGHT
	} from '$lib/chat';
	import { onMount } from 'svelte';

	let open = $state(false);
	let inputText = $state('');
	let showEmotes = $state(false);

	// Pagination
	let currentSeriesIdx = $state(0);
	let currentPage = $state(0);
	const PER_PAGE = 12;

	let config = $derived($emoteConfig);
	let seriesList = $derived(config?.series ?? []);
	let currentSeries = $derived(seriesList[currentSeriesIdx] ?? null);
	let totalPages = $derived(currentSeries ? Math.ceil(currentSeries.emotes.length / PER_PAGE) : 0);
	let paginatedEmotes = $derived(
		currentSeries
			? currentSeries.emotes.slice(currentPage * PER_PAGE, (currentPage + 1) * PER_PAGE)
			: []
	);

	onMount(() => {
		loadEmoteConfig();
	});

	let weight = $derived(chatTextWeight(inputText));
	let overLimit = $derived(weight > CHAT_MAX_WEIGHT);

	function submit() {
		const raw = inputText.trim();
		if (!raw) return;
		const text = truncateChatText(raw);
		if (text.startsWith('/')) {
			const emoteId = EMOTE_SLUGS[text.slice(1).toLowerCase()];
			if (emoteId) {
				sendEmote(emoteId);
				inputText = '';
				return;
			}
		}
		sendChat(text);
		inputText = '';
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			submit();
		}
		e.stopPropagation();
	}

	function selectSeries(idx: number) {
		currentSeriesIdx = idx;
		currentPage = 0;
	}

	function nextPage() {
		if (currentPage < totalPages - 1) currentPage++;
	}

	function prevPage() {
		if (currentPage > 0) currentPage--;
	}

	function sendAndClose(emoteId: string) {
		sendEmote(emoteId);
		showEmotes = false;
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
					class:over-limit={overLimit}
					type="text"
					placeholder="Say something…"
					maxlength="64"
					bind:value={inputText}
					onkeydown={onKeydown}
				/>
				<span class="chat-counter" class:over-limit={overLimit}>{weight}/{CHAT_MAX_WEIGHT}</span>
				<button class="chat-send" onclick={submit}>Send</button>
			</div>
		</div>
	{/if}

	{#if showEmotes && config}
		<!-- Series tabs -->
		<div class="series-tabs">
			{#each seriesList as series, idx}
				<button
					class="series-tab"
					class:active={idx === currentSeriesIdx}
					onclick={() => selectSeries(idx)}
				>
					{series.name}
				</button>
			{/each}
		</div>

		<!-- Emote grid with pagination -->
		{#if currentSeries}
			<div class="emote-panel">
				<div class="emote-grid">
					{#each paginatedEmotes as emote}
						<button class="emote-btn" onclick={() => sendAndClose(emote.id)} title={emote.label}>
							<img src={emote.src} alt={emote.label} class="emote-thumb" />
						</button>
					{/each}
				</div>

				{#if totalPages > 1}
					<div class="pagination">
						<button class="page-btn" onclick={prevPage} disabled={currentPage === 0}>◀</button>
						<span class="page-info">{currentPage + 1} / {totalPages}</span>
						<button class="page-btn" onclick={nextPage} disabled={currentPage >= totalPages - 1}>▶</button>
					</div>
				{/if}
			</div>
		{/if}
	{/if}
</div>

<style>
	#social-panel {
		position: fixed;
		bottom: 12px;
		left: 12px;
		z-index: 20;
		font-size: 0.9rem;
	}

	.social-header {
		display: flex;
		gap: 2px;
	}

	.social-tab {
		background: rgba(20, 20, 30, 0.55);
		border: 1px solid rgba(255, 255, 255, 0.18);
		border-bottom: none;
		border-radius: 0.5rem 0.5rem 0 0;
		padding: 10px 18px;
		color: #ccc;
		cursor: pointer;
		font-size: 0.95rem;
		min-height: 40px;
		transition: all 0.15s;
	}

	.social-tab:first-child {
		border-radius: 0.5rem 0 0 0;
	}

	.social-tab:last-child {
		border-radius: 0 0.5rem 0 0;
	}

	.social-tab.active {
		background: rgba(30, 30, 45, 0.7);
		color: #fff;
		border-color: rgba(255, 255, 255, 0.3);
	}

	.social-content {
		background: rgba(15, 15, 22, 0.65);
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-radius: 0 0.5rem 0.5rem 0.5rem;
		overflow: hidden;
		backdrop-filter: blur(6px);
		min-width: 320px;
	}

	.log-entries {
		max-height: 220px;
		overflow-y: auto;
		padding: 10px 12px;
		display: flex;
		flex-direction: column;
		gap: 4px;
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
		align-items: center;
		border-top: 1px solid rgba(255, 255, 255, 0.12);
		padding: 10px 12px;
		gap: 8px;
	}

	.chat-input {
		flex: 1;
		background: rgba(255, 255, 255, 0.1);
		border: 1px solid rgba(255, 255, 255, 0.2);
		border-radius: 0.4rem;
		color: #eee;
		font-size: 0.95rem;
		padding: 8px 10px;
		outline: none;
		min-height: 36px;
	}
	.chat-input:focus {
		border-color: rgba(255, 255, 255, 0.35);
	}
	.chat-input.over-limit {
		border-color: #e57373;
	}

	.chat-counter {
		color: #888;
		font-size: 0.8rem;
		align-self: center;
		min-width: 3em;
		text-align: right;
	}
	.chat-counter.over-limit {
		color: #e57373;
	}

	.chat-send {
		background: rgba(255, 255, 255, 0.15);
		border: 1px solid rgba(255, 255, 255, 0.25);
		border-radius: 0.4rem;
		color: #eee;
		cursor: pointer;
		font-size: 0.9rem;
		padding: 8px 16px;
		min-height: 36px;
	}
	.chat-send:hover {
		background: rgba(255, 255, 255, 0.18);
	}

	/* Series tabs */
	.series-tabs {
		display: flex;
		gap: 3px;
		background: rgba(15, 15, 22, 0.65);
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-bottom: none;
		border-radius: 0.5rem 0.5rem 0 0;
		padding: 6px 6px 0 6px;
		backdrop-filter: blur(6px);
	}

	.series-tab {
		background: rgba(255, 255, 255, 0.08);
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-bottom: none;
		border-radius: 0.4rem 0.4rem 0 0;
		padding: 8px 14px;
		color: #bbb;
		cursor: pointer;
		font-size: 0.85rem;
		min-height: 36px;
		transition: all 0.1s;
	}

	.series-tab.active {
		background: rgba(255, 255, 255, 0.15);
		color: #fff;
	}

	.series-tab:hover:not(.active) {
		background: rgba(255, 255, 255, 0.1);
	}

	/* Emote panel */
	.emote-panel {
		background: rgba(15, 15, 22, 0.65);
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-top: none;
		border-radius: 0 0.5rem 0.5rem 0.5rem;
		padding: 12px;
		backdrop-filter: blur(6px);
	}

	.emote-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 10px;
	}

	.emote-btn {
		background: none;
		border: 1px solid transparent;
		border-radius: 0.5rem;
		cursor: pointer;
		padding: 6px;
		transition: all 0.1s;
	}

	.emote-btn:hover {
		background: rgba(255, 255, 255, 0.12);
		border-color: rgba(255, 255, 255, 0.25);
		transform: scale(1.05);
	}

	.emote-thumb {
		display: block;
		width: 64px;
		height: 64px;
		border-radius: 0.4rem;
	}

	/* Pagination */
	.pagination {
		display: flex;
		justify-content: center;
		align-items: center;
		gap: 8px;
		margin-top: 8px;
		padding-top: 6px;
		border-top: 1px solid rgba(255, 255, 255, 0.08);
	}

	.page-btn {
		background: rgba(255, 255, 255, 0.1);
		border: 1px solid rgba(255, 255, 255, 0.2);
		border-radius: 0.4rem;
		color: #ccc;
		cursor: pointer;
		padding: 6px 12px;
		font-size: 0.85rem;
		min-width: 32px;
		min-height: 32px;
	}

	.page-btn:hover:not(:disabled) {
		background: rgba(255, 255, 255, 0.15);
		color: #fff;
	}

	.page-btn:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}

	.page-info {
		color: #888;
		font-size: 0.7rem;
	}
</style>