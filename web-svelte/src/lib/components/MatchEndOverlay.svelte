<script lang="ts">
	import { gameState, agariResult, sendAction, getMyId, getOppId, getMyDisplayName, isOwner } from '$lib/ws';

	let s = $derived($gameState);
	let result = $derived(s.matchResult);
	let myId = $derived(getMyId());
	let oppId = $derived(getOppId());
	let amOwner = $derived($isOwner);

	let isWinner = $derived(result?.winnerId === myId);
	let isDraw   = $derived(result !== null && result.winnerId === null);

	let myScore  = $derived(result?.finalScores[myId] ?? 0);
	let oppScore = $derived(result?.finalScores[oppId] ?? 0);

	let reasonLabel = $derived.by(() => {
		if (!result) return '';
		if (result.reason === 'point_zero') return '点数耗尽 — Points depleted';
		if (result.reason === 'round_limit_reached') return '轮数到上限 — Round limit reached';
		return result.reason;
	});

	function playAgain() {
		agariResult.set(null);
		sendAction('continue_game');
	}

	/** 房主：解散房间 → 广播倒计时给对手，自身返回大厅 */
	function dissolveRoom() {
		sendAction('end_game');
	}

	/** 非房主：静默离开，房间保留，房主等待新人加入 */
	function leaveRoom() {
		// 乐观更新：立即跳转大厅，服务端随后会关闭 WS
		agariResult.set(null);
		gameState.update((s) => ({ ...s, phase: 'lobby', matchResult: null }));
		sendAction('leave_room');
	}
</script>

{#if result}
	<div class="overlay">
		<div class="overlay-box">
			{#if isDraw}
				<h2><span class="result-draw">平局 — Draw</span></h2>
			{:else if isWinner}
				<h2><span class="result-win">你赢了 — You Win!</span></h2>
			{:else}
				<h2><span class="result-lose">你输了 — You Lose</span></h2>
			{/if}

			<p class="reason-label">{reasonLabel}</p>

			<div class="score-table">
				<div class="score-row">
					<span class="score-name">{getMyDisplayName()} (你)</span>
					<span class="score-val" class:negative={myScore < 0}>{myScore.toLocaleString()}</span>
				</div>
				<div class="score-row">
					<span class="score-name">{s.oppDisplayName || '对手'}</span>
					<span class="score-val" class:negative={oppScore < 0}>{oppScore.toLocaleString()}</span>
				</div>
			</div>

			<div class="btn-row">
				<button class="btn btn-primary" onclick={playAgain}>再来一局</button>

				{#if amOwner}
					<!-- 房主：解散房间（对手看到倒计时提示框） -->
					<button class="btn btn-dissolve" onclick={dissolveRoom}>解散房间</button>
				{:else}
					<!-- 非房主：静默离开，房间留给房主等待新人 -->
					<button class="btn btn-secondary" onclick={leaveRoom}>返回大厅</button>
				{/if}
			</div>

			{#if amOwner}
				<p class="owner-hint">解散房间后，对手将收到 10 秒倒计时提示</p>
			{/if}
		</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.72);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 200;
	}

	.overlay-box {
		background: #1a2332;
		border: 1px solid #334;
		border-radius: 12px;
		padding: 2rem 2.5rem;
		min-width: 300px;
		text-align: center;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	h2 {
		margin: 0;
		font-size: 1.6rem;
	}

	.result-win  { color: #4caf50; }
	.result-lose { color: #e53935; }
	.result-draw { color: #aaa; }

	.reason-label {
		margin: 0;
		font-size: 0.82rem;
		color: #888;
	}

	.score-table {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		margin: 0.25rem 0;
	}

	.score-row {
		display: flex;
		justify-content: space-between;
		font-size: 1rem;
		color: #ddd;
		gap: 2rem;
	}

	.score-name { text-align: left; }

	.score-val {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.score-val.negative { color: #e53935; }

	.btn-row {
		display: flex;
		gap: 0.75rem;
		justify-content: center;
		margin-top: 0.25rem;
	}

	.btn-secondary {
		background: transparent;
		border: 1px solid #555;
		color: #bbb;
		padding: 0.5rem 1.1rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.95rem;
		transition: border-color 0.15s, color 0.15s;
	}

	.btn-secondary:hover {
		border-color: #aaa;
		color: #eee;
	}

	.btn-dissolve {
		background: transparent;
		border: 1px solid #c0392b;
		color: #e57373;
		padding: 0.5rem 1.1rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.95rem;
		transition: background 0.15s, border-color 0.15s, color 0.15s;
	}

	.btn-dissolve:hover {
		background: #c0392b22;
		border-color: #e57373;
		color: #ff8a80;
	}

	.owner-hint {
		margin: -0.4rem 0 0;
		font-size: 0.74rem;
		color: #556;
		line-height: 1.4;
	}
</style>
