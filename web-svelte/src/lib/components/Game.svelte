<script lang="ts">
	import { gameState, sendAction, getMyId, getOppId, getMyDisplayName } from '$lib/ws';
	import Hand from './Hand.svelte';
	import OpponentHand from './OpponentHand.svelte';
	import Kawa from './Kawa.svelte';
	import Fuuro from './Fuuro.svelte';
	import AgariOverlay from './AgariOverlay.svelte';
	import MatchEndOverlay from './MatchEndOverlay.svelte';
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
		// Riichi: can only discard the tile just drawn (last tile)
		if (s.myRiichi && idx !== s.myHand.length - 1) {
			return;
		}
		if (s.selectedIdx === idx) {
			sendAction('discard', idx);
			gameState.update((prev) => ({ ...prev, selectedIdx: null }));
		} else {
			gameState.update((prev) => ({ ...prev, selectedIdx: idx }));
		}
	}

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
	<!-- Top zone: hand pinned to top, fuuro on left -->
	<div class="zone-top">
		<div class="hand-with-fuuro">
			<Fuuro melds={s.oppFuuro} tileRotation={2} />
			<OpponentHand count={oppHandSize} />
		</div>
	</div>

	<!-- Mid zone: kawa + center panel + kawa, no flex growth -->
	<div class="zone-mid">
		<Kawa kawa={s.oppKawa} tileRotation={2} highlightLast={isMyTurn && s.turnStage === 'after_discard'} isOpponent />

		<div id="center-panel">
			<div class="cp-player">
				<span class="player-name">{s.oppDisplayName || '???'}</span>
				<span class="player-points">{s.oppPoints.toLocaleString()}</span>
				{#if s.phase === 'playing' && !s.myIsOya}<span class="badge">親</span>{/if}
				{#if s.oppRiichi}<span class="badge badge-riichi">立直</span>{/if}
			</div>
			<div class="cp-divider"></div>
			<div class="cp-game-info">
				<span class="cp-stat">{s.phase === 'playing' ? `Wall: ${s.wallCount}` : ''}</span>
				<span class="cp-stat">{s.kyoutaku > 0 ? `立直棒×${s.kyoutaku}` : ''}</span>
			</div>
			<span class="center-mid">{turnLabel}</span>
			<div class="cp-divider"></div>
			<div class="cp-player">
				<span class="player-name">{getMyDisplayName()}</span>
				<span class="player-points">{s.myPoints.toLocaleString()}</span>
				{#if s.phase === 'playing' && s.myIsOya}<span class="badge">親</span>{/if}
				{#if s.myRiichi}<span class="badge badge-riichi">立直</span>{/if}
			</div>
		</div>

		<Kawa kawa={s.myKawa} highlightLast={!isMyTurn && s.turnStage === 'after_discard'} />
	</div>

	<!-- Bottom zone: grows upward, hand pinned to bottom, fuuro on right -->
	<div class="zone-bot">
		<div class="hand-with-fuuro">
			<Hand
				tiles={s.myHand}
				interactive={s.phase === 'playing' && isMyTurn && s.turnStage === 'after_draw'}
				selectedIdx={s.selectedIdx}
				turnStage={s.turnStage}
				onselect={handleSelect}
			/>
			<Fuuro melds={s.myFuuro} />
		</div>
	</div>

	<!-- Action bar pinned to bottom -->
	<div class="action-bar">
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
			{#if isMyTurn && s.turnStage === 'after_discard' && s.phase === 'playing'}
				<button class="btn btn-ron" onclick={() => sendAction('ron')}>Ron (R)</button>
				<button class="btn btn-action" onclick={() => sendAction('skip_ron')}>Skip (S)</button>
			{/if}
		{/if}
	</div>

	{#if !s.matchResult}
		<AgariOverlay />
	{/if}
	<MatchEndOverlay />
	<MessageLog />
</div>
