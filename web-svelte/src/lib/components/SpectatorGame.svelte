<script lang="ts">
	import { spectatorState } from '$lib/ws';
	import Tile from './Tile.svelte';
	import MessageLog from './MessageLog.svelte';
	import type { SpectatorPlayerData } from '$lib/types';

	let state = $derived($spectatorState);
	let playerEntries = $derived(Object.entries(state.players));

	function getTurnLabel(pid: string): string {
		if (!state.currentPlayer) return '';
		if (state.currentPlayer !== pid) return '';
		const stage = state.turnStage;
		if (stage === 'after_draw') return '🀄 Drawing';
		if (stage === 'after_discard') return '⏳ Waiting Ron/Skip';
		if (stage === 'before_draw') return '⏳ Before Draw';
		return '▶ Acting';
	}

	function pointsColor(point: number): string {
		if (point < 0) return 'negative';
		if (point >= 150000) return 'positive';
		return '';
	}
</script>

<div class="spectator-root">
	<header class="spectator-header">
		<span class="spec-badge">👁 Spectating</span>
		<span class="spec-info">
			Round {state.roundNo + 1} / {state.roundLimit}
			&nbsp;·&nbsp;
			Wall: {state.wallCount}
			{#if state.kyoutaku > 0}
				&nbsp;·&nbsp;Kyoutaku: {state.kyoutaku}
			{/if}
		</span>
	</header>

	<div class="players-area">
		{#each playerEntries as [pid, player] (pid)}
			{@const turnLabel = getTurnLabel(pid)}
			<div class="player-panel" class:active-turn={!!turnLabel}>
				<!-- Player header -->
				<div class="player-header">
					<span class="player-name">
						{player.display_name || pid.slice(0, 8)}
						{#if player.is_oya}
							<span class="oya-badge">East</span>
						{/if}
						{#if player.is_riichi}
							<span class="riichi-badge">RIICHI</span>
						{/if}
					</span>
					<span class="player-points {pointsColor(player.point)}">
						{player.point.toLocaleString()}
					</span>
					{#if turnLabel}
						<span class="turn-label">{turnLabel}</span>
					{/if}
				</div>

				<!-- Hand (face-up for spectators) -->
				<div class="section-label">Hand ({player.hand.length})</div>
				<div class="hand-row">
					{#each player.hand as card, i (i)}
						<Tile {card} rotation={0} />
					{/each}
				</div>

				<!-- Fuuro -->
				{#if player.fuuro.length > 0}
					<div class="section-label">Melds</div>
					<div class="fuuro-row">
						{#each player.fuuro as meld, mi (mi)}
							<span class="meld-group">
								{#each meld as card, ci (ci)}
									<Tile {card} rotation={0} />
								{/each}
							</span>
						{/each}
					</div>
				{/if}

				<!-- Kawa -->
				{#if player.kawa.length > 0}
					<div class="section-label">Discards</div>
					<div class="kawa-row">
						{#each player.kawa as entry, i (i)}
							<Tile card={entry.card} rotation={entry.isRiichi ? 1 : 0} />
						{/each}
					</div>
				{/if}
			</div>
		{/each}
	</div>

	{#if playerEntries.length === 0}
		<div class="waiting-msg">Waiting for the game to start…</div>
	{/if}

	<div class="spec-log">
		<MessageLog />
	</div>
</div>

<style>
	.spectator-root {
		display: flex;
		flex-direction: column;
		min-height: 100vh;
		background: #1a1a2e;
		color: #e0e0e0;
		padding: 0.75rem;
		gap: 0.75rem;
		box-sizing: border-box;
	}

	.spectator-header {
		display: flex;
		align-items: center;
		gap: 1rem;
		background: #16213e;
		border-radius: 6px;
		padding: 0.5rem 1rem;
		font-size: 0.85rem;
	}

	.spec-badge {
		background: #e94560;
		color: #fff;
		border-radius: 4px;
		padding: 0.15rem 0.5rem;
		font-weight: 600;
		font-size: 0.8rem;
	}

	.spec-info {
		color: #aaa;
	}

	.players-area {
		display: flex;
		gap: 1rem;
		flex: 1;
		flex-wrap: wrap;
	}

	.player-panel {
		flex: 1;
		min-width: 300px;
		background: #16213e;
		border-radius: 8px;
		padding: 0.75rem 1rem;
		border: 2px solid transparent;
		transition: border-color 0.2s;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.player-panel.active-turn {
		border-color: #e94560;
	}

	.player-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
		margin-bottom: 0.25rem;
	}

	.player-name {
		font-weight: 700;
		font-size: 1rem;
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}

	.oya-badge {
		background: #f0a500;
		color: #000;
		border-radius: 3px;
		padding: 0.05rem 0.35rem;
		font-size: 0.7rem;
		font-weight: 600;
	}

	.riichi-badge {
		background: #e94560;
		color: #fff;
		border-radius: 3px;
		padding: 0.05rem 0.35rem;
		font-size: 0.7rem;
		font-weight: 600;
	}

	.player-points {
		margin-left: auto;
		font-size: 1.1rem;
		font-weight: 700;
		font-family: monospace;
	}

	.player-points.negative { color: #e94560; }
	.player-points.positive { color: #4ecca3; }

	.turn-label {
		font-size: 0.75rem;
		color: #e94560;
		background: rgba(233, 69, 96, 0.15);
		border-radius: 4px;
		padding: 0.1rem 0.4rem;
	}

	.section-label {
		font-size: 0.7rem;
		color: #888;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-top: 0.25rem;
	}

	.hand-row, .kawa-row {
		display: flex;
		flex-wrap: wrap;
		gap: 2px;
	}

	.fuuro-row {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.meld-group {
		display: flex;
		gap: 1px;
		background: rgba(255,255,255,0.05);
		border-radius: 4px;
		padding: 2px;
	}

	.waiting-msg {
		text-align: center;
		color: #888;
		padding: 3rem;
		font-size: 1.1rem;
	}

	.spec-log {
		max-height: 150px;
		overflow-y: auto;
	}
</style>
