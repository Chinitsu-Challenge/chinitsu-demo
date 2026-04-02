<script lang="ts">
	import type { ReplayFrame } from '$lib/types';
	import { frameToGameState } from '$lib/replayView';
	import Game from './Game.svelte';

	let fileError = $state('');
	let loading = $state(false);
	let frames = $state<ReplayFrame[]>([]);
	let step = $state(0);
	let povIdx = $state(0);

	const base = $derived(
		typeof window !== 'undefined'
			? `${window.location.protocol}//${window.location.host}`
			: ''
	);

	async function onFile(e: Event) {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		fileError = '';
		loading = true;
		frames = [];
		try {
			const text = await file.text();
			const json = JSON.parse(text) as unknown;
			const res = await fetch(`${base}/api/replay/build-frames`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(json)
			});
			if (!res.ok) {
				const err = (await res.json().catch(() => ({}))) as { detail?: string };
				throw new Error(err.detail || res.statusText);
			}
			const data = (await res.json()) as { frames: ReplayFrame[] };
			frames = data.frames;
			step = 0;
		} catch (err) {
			fileError = err instanceof Error ? err.message : String(err);
		} finally {
			loading = false;
			input.value = '';
		}
	}

	const frame = $derived(frames[step] ?? null);
	const povId = $derived(frame?.player_ids[povIdx] ?? '');
	const oppIdx = $derived(1 - povIdx);
	const oppId = $derived(frame?.player_ids[oppIdx] ?? '');
	const replayGs = $derived(frame ? frameToGameState(frame, povId) : null);
	const dn = $derived(frame?.display_names ?? {});

	function prev() {
		step = Math.max(0, step - 1);
	}
	function next() {
		step = Math.min(frames.length - 1, step + 1);
	}
	function swapPov() {
		povIdx = 1 - povIdx;
	}
</script>

<div class="replay-root screen">
	<div class="replay-toolbar">
		<a class="link-back" href="/">← Lobby</a>
		<label class="file-label">
			Load .json
			<input type="file" accept="application/json,.json" class="file-input" onchange={onFile} />
		</label>
		{#if loading}
			<span class="hint">Building frames…</span>
		{/if}
		{#if fileError}
			<span class="err">{fileError}</span>
		{/if}
	</div>

	{#if frames.length > 0 && replayGs && frame}
		<div class="replay-controls">
			<button class="btn btn-action" type="button" onclick={prev} disabled={step <= 0}>Prev</button>
			<input
				type="range"
				class="replay-slider"
				min="0"
				max={frames.length - 1}
				value={step}
				oninput={(e) => (step = +(e.currentTarget as HTMLInputElement).value)}
			/>
			<button class="btn btn-action" type="button" onclick={next} disabled={step >= frames.length - 1}>
				Next
			</button>
			<span class="step-label">Step {step} / {frames.length - 1}</span>
			<button class="btn btn-action" type="button" onclick={swapPov}>Swap seats</button>
		</div>
		{#if frame.last_event}
			<div class="last-event">
				Last: <code>{frame.last_event.action}</code>
				{#if frame.last_event.card_idx != null}(idx {frame.last_event.card_idx}){/if}
				— {dn[frame.last_event.player_id] || frame.last_event.player_id.slice(0, 8)}
			</div>
		{/if}

		<div class="replay-board">
			<Game
				replayState={replayGs}
				replayMyId={povId}
				replayOppId={oppId}
				replayMyName={dn[povId] || povId.slice(0, 8)}
				replayOppName={dn[oppId] || oppId.slice(0, 8)}
				showMessageLog={false}
				showAgariOverlay={false}
				disableShortcuts={true}
			/>
		</div>

		{#if frame.ryukyoku && frame.tenpai}
			<div class="replay-banner">流局 — Exhaustive draw</div>
		{:else if frame.agari !== undefined}
			<div class="replay-banner agari">
				{#if frame.agari}
					Agari — {frame.han ?? '?'} han / {frame.fu ?? '?'} fu — {(frame.agari_point ?? 0).toLocaleString()} pts
					{#if frame.yaku?.length}
						<div class="yaku">{frame.yaku.join(', ')}</div>
					{/if}
				{:else}
					No agari — penalty {(frame.agari_point ?? 0).toLocaleString()} pts
				{/if}
			</div>
		{/if}
	{:else if !loading}
		<p class="hint center">Export a replay from the table after a round ends (“Export replay”), then open the file here.</p>
	{/if}
</div>

<style>
	.replay-root {
		display: flex;
		flex-direction: column;
		background: radial-gradient(ellipse at center, var(--felt) 0%, var(--felt-dark) 100%);
		min-height: 100%;
	}
	.replay-toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.75rem;
		padding: 0.5rem 1rem;
		background: rgba(0, 0, 0, 0.35);
	}
	.link-back {
		color: var(--accent);
		text-decoration: none;
		font-size: 0.95rem;
	}
	.link-back:hover {
		text-decoration: underline;
	}
	.file-label {
		cursor: pointer;
		background: var(--btn-primary);
		color: var(--text-dark);
		padding: 0.35rem 0.75rem;
		border-radius: 8px;
		font-size: 0.9rem;
	}
	.file-input {
		display: none;
	}
	.hint {
		font-size: 0.85rem;
		opacity: 0.8;
	}
	.hint.center {
		padding: 2rem;
		text-align: center;
	}
	.err {
		color: var(--danger);
		font-size: 0.85rem;
	}
	.replay-controls {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
		padding: 0.35rem 1rem;
	}
	.replay-slider {
		flex: 1;
		min-width: 120px;
		max-width: 320px;
	}
	.step-label {
		font-size: 0.85rem;
		opacity: 0.9;
	}
	.last-event {
		padding: 0 1rem 0.35rem;
		font-size: 0.8rem;
		opacity: 0.85;
	}
	.replay-board {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.replay-banner {
		margin: 0 1rem 0.75rem;
		padding: 0.5rem 0.75rem;
		background: rgba(0, 0, 0, 0.45);
		border-radius: 8px;
		font-size: 0.9rem;
	}
	.replay-banner.agari {
		border: 1px solid var(--accent);
	}
	.yaku {
		margin-top: 0.25rem;
		font-size: 0.8rem;
		opacity: 0.9;
	}
</style>
