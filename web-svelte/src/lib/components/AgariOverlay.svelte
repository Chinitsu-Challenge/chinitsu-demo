<script lang="ts">
	import { agariResult, sendAction, gameState } from '$lib/ws';

	let result = $derived($agariResult);

	function startNewGame() {
		agariResult.set(null);
		sendAction('start_new');
	}
</script>

{#if result}
	<div class="overlay">
		<div class="overlay-box">
			{#if result.agari}
				<h2>
					{#if result.isMe}
						<span class="agari-win">{result.action === 'tsumo' ? 'Tsumo' : 'Ron'}! You Win!</span>
					{:else}
						<span class="agari-lose">{result.action === 'tsumo' ? 'Tsumo' : 'Ron'} — You Lose</span>
					{/if}
				</h2>
				{#if result.hand}
					<div class="agari-hand">
						{#each result.hand as card}
							<img
								class="agari-tile"
								src="/assets/{card}_{result.isMe ? 0 : 2}.png"
								alt={card}
							/>
						{/each}
					</div>
				{/if}
				<div id="agari-details">
					<div>{result.han} Han / {result.fu} Fu</div>
					<div class="point-val">{result.point.toLocaleString()} pts</div>
					{#if result.yaku}
						<div>
							{#each result.yaku as y, i}
								<span class="yaku-list">{y}</span>{#if i < result.yaku.length - 1}, {/if}
							{/each}
						</div>
					{/if}
				</div>
			{:else}
				<h2><span class="agari-fail">No Agari</span></h2>
				<div id="agari-details">
					<div>{result.isMe ? 'You' : 'Opponent'} declared but had no valid hand.</div>
					<div class="point-val" style="color:var(--danger)">{Math.abs(result.point).toLocaleString()} pts penalty</div>
				</div>
			{/if}
			<button class="btn btn-primary" onclick={startNewGame}>New Game</button>
		</div>
	</div>
{/if}
