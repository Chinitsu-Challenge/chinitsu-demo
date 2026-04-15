<script lang="ts">
	import { agariResult, sendAction, gameState, getMyId, getOppId } from '$lib/ws';

	let result = $derived($agariResult);
	let myId = $derived(getMyId());
	let oppId = $derived(getOppId());

	function startNewGame() {
		agariResult.set(null);
		sendAction('start_new');
	}
</script>

{#if result}
	<div class="overlay">
		<div class="overlay-box">
			{#if result.action === 'ryukyoku'}
				<h2><span class="agari-fail">流局 — Exhaustive Draw</span></h2>
				{#if result.tenpai}
					<div id="agari-details">
						{#each [[myId, '你 / You'], [oppId, '对手 / Opponent']] as [pid, label]}
							{@const info = result.tenpai[pid]}
							{#if info}
								<div style="margin-bottom:0.5rem">
									<span>{label}：</span>
									<span style="color:{info.is_tenpai ? 'var(--success, #4caf50)' : 'var(--danger)'}">
										{info.is_tenpai ? '聴牌 Tenpai' : '不聴 No-ten'}
									</span>
									{#if info.is_tenpai && info.hand.length}
										<div class="agari-hand" style="margin-top:0.25rem">
											{#each info.hand as card}
												<img class="agari-tile" src="/assets/{card}_0.png" alt={card} />
											{/each}
										</div>
									{/if}
								</div>
							{/if}
						{/each}
					</div>
				{/if}
			{:else if result.agari}
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
								src="/assets/{card}_0.png"
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
