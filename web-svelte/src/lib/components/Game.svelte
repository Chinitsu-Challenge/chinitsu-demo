<script lang="ts">
	import { gameState, sendAction, getMyId, getOppId, getMyDisplayName } from '$lib/ws';
	import Hand from './Hand.svelte';
	import OpponentHand from './OpponentHand.svelte';
	import Kawa from './Kawa.svelte';
	import Fuuro from './Fuuro.svelte';
	import AgariOverlay from './AgariOverlay.svelte';
	import MessageLog from './MessageLog.svelte';
	import { onMount } from 'svelte';

	let s = $derived($gameState);
	let myId = $derived(getMyId());
	let oppId = $derived(getOppId());
	let isMyTurn = $derived(s.currentPlayer === myId);

	let turnLabel = $derived.by(() => {
		if (s.phase === 'waiting') return 'Waiting for opponent...';
		if (s.phase === 'waiting_new_game') return 'Waiting for opponent to start...';
		if (s.phase === 'ended') return 'Round ended';
		if (s.phase !== 'playing') return '';
		if (!isMyTurn) return "Opponent's turn...";
		if (s.turnStage === 'before_draw') return 'Your turn \u2014 Draw a tile';
		if (s.turnStage === 'after_draw') return 'Your turn \u2014 Select & discard';
		if (s.turnStage === 'after_discard') return 'Opponent discarded \u2014 Ron or Skip?';
		return '';
	});

	let oppHandSize = $derived.by(() => {
		if (s.phase !== 'playing' && s.phase !== 'ended') return 0;
		const kanCount = s.oppFuuro.length;
		let base = 13 - kanCount * 3;
		if (s.currentPlayer === oppId && s.turnStage === 'after_draw') base++;
		return Math.max(0, base);
	});

	function handleSelect(idx: number) {
		if (s.selectedIdx === idx) {
			sendAction('discard', idx);
			gameState.update((prev) => ({ ...prev, selectedIdx: null }));
		} else {
			gameState.update((prev) => ({ ...prev, selectedIdx: idx }));
		}
	}

	// Keyboard shortcuts
	onMount(() => {
		function onKey(e: KeyboardEvent) {
			const st = $gameState;
			if (st.phase !== 'playing') return;
			const isMy = st.currentPlayer === getMyId();

			if (e.key === 'd' && isMy && st.turnStage === 'before_draw') sendAction('draw');
			if (e.key === 't' && isMy && st.turnStage === 'after_draw') sendAction('tsumo');
			if (e.key === 'r' && isMy && st.turnStage === 'after_discard') sendAction('ron');
			if (e.key === 's' && isMy && st.turnStage === 'after_discard') sendAction('skip_ron');
			if (e.key === 'Escape') gameState.update((prev) => ({ ...prev, selectedIdx: null }));
		}
		document.addEventListener('keydown', onKey);
		return () => document.removeEventListener('keydown', onKey);
	});
</script>

<div id="game" class="screen">
	<!-- Opponent bar -->
	<div class="player-bar opponent-bar">
		<span class="player-name">{s.oppDisplayName || '???'}</span>
		<span class="player-points">{s.oppPoints.toLocaleString()}</span>
		{#if s.phase === 'playing' && !s.myIsOya}
			<span class="badge">親</span>
		{/if}
		{#if s.oppRiichi}
			<span class="badge badge-riichi">立直</span>
		{/if}
	</div>

	<!-- Opponent hand -->
	<OpponentHand count={oppHandSize} />

	<!-- Opponent fuuro -->
	<Fuuro melds={s.oppFuuro} />

	<!-- Opponent kawa -->
	<Kawa kawa={s.oppKawa} />

	<!-- Center info -->
	<div id="center-info">
		<span>{s.phase === 'playing' ? `Wall: ${s.wallCount}` : ''}</span>
		<span class="center-mid">{turnLabel}</span>
		<span>{s.kyoutaku > 0 ? `Riichi sticks: ${s.kyoutaku}` : ''}</span>
	</div>

	<!-- My kawa -->
	<Kawa kawa={s.myKawa} />

	<!-- My fuuro -->
	<Fuuro melds={s.myFuuro} />

	<!-- My hand -->
	<Hand
		tiles={s.myHand}
		interactive={s.phase === 'playing' && isMyTurn && s.turnStage === 'after_draw'}
		selectedIdx={s.selectedIdx}
		turnStage={s.turnStage}
		onselect={handleSelect}
	/>

	<!-- My bar -->
	<div class="player-bar my-bar">
		<div class="my-info">
			<span class="player-name">{getMyDisplayName()}</span>
			<span class="player-points">{s.myPoints.toLocaleString()}</span>
			{#if s.phase === 'playing' && s.myIsOya}
				<span class="badge">親</span>
			{/if}
			{#if s.myRiichi}
				<span class="badge badge-riichi">立直</span>
			{/if}
		</div>
		<div class="action-buttons">
			{#if s.phase === 'waiting'}
				<button class="btn btn-action" onclick={() => sendAction('start')}>Start Game</button>
			{:else if s.phase === 'ended'}
				<button class="btn btn-action" onclick={() => sendAction('start_new')}>New Game</button>
			{:else if s.phase === 'waiting_new_game'}
				<span class="waiting-label">Waiting for opponent...</span>
			{/if}
			{#if s.phase === 'playing'}
				{#if isMyTurn && s.turnStage === 'before_draw'}
					<button class="btn btn-action" onclick={() => sendAction('draw')}>Draw (D)</button>
				{/if}
				{#if isMyTurn && s.turnStage === 'after_draw'}
					<button class="btn btn-tsumo" onclick={() => sendAction('tsumo')}>Tsumo (T)</button>
					{#if !s.myRiichi}
						<button
							class="btn btn-riichi"
							disabled={s.selectedIdx === null}
							onclick={() => { sendAction('riichi', s.selectedIdx); gameState.update(p => ({...p, selectedIdx: null})); }}
						>Riichi</button>
						<button
							class="btn btn-kan"
							disabled={s.selectedIdx === null}
							onclick={() => { sendAction('kan', s.selectedIdx); gameState.update(p => ({...p, selectedIdx: null})); }}
						>Kan</button>
					{/if}
				{/if}
				{#if isMyTurn && s.turnStage === 'after_discard'}
					<button class="btn btn-ron" onclick={() => sendAction('ron')}>Ron (R)</button>
					<button class="btn btn-action" onclick={() => sendAction('skip_ron')}>Skip (S)</button>
				{/if}
			{/if}
		</div>
	</div>

	<AgariOverlay />
	<MessageLog />
</div>
