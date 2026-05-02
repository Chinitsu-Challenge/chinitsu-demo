<script lang="ts">
	import { wsError, agariResult, gameState } from '$lib/ws';

	let err = $derived($wsError);

	function returnToLobby() {
		agariResult.set(null);
		wsError.set(null);
		gameState.set({
			phase: 'lobby',
			myHand: [],
			myIsOya: false,
			myPoints: 150000,
			oppPoints: 150000,
			myRiichi: false,
			oppRiichi: false,
			myKawa: [],
			oppKawa: [],
			myFuuro: [],
			oppFuuro: [],
			currentPlayer: null,
			turnStage: null,
			selectedIdx: null,
			wallCount: 36,
			kyoutaku: 0,
			roundNo: 0,
			roundLimit: 8,
			oppDisplayName: '',
			matchResult: null,
		});
	}
</script>

{#if err}
	<div class="overlay" role="alertdialog" aria-live="assertive">
		<div class="box">
			<div class="icon">⚠</div>
			<h2>连接已断开</h2>
			<p class="msg">{err.message}</p>
			<button class="btn-lobby" onclick={returnToLobby}>返回大厅</button>
		</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.82);
		display: flex;
		align-items: center;
		justify-content: center;
		/* Highest z-index — must sit above every other overlay */
		z-index: 500;
	}

	.box {
		background: #111c2b;
		border: 1px solid #c0392b;
		border-radius: 14px;
		padding: 2.2rem 2.8rem;
		min-width: 300px;
		max-width: 420px;
		text-align: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
		box-shadow: 0 8px 40px rgba(0, 0, 0, 0.6);
		animation: pop-in 0.18s ease;
	}

	@keyframes pop-in {
		from { opacity: 0; transform: scale(0.93); }
		to   { opacity: 1; transform: scale(1); }
	}

	.icon {
		font-size: 2.4rem;
		line-height: 1;
		color: #e57373;
	}

	h2 {
		margin: 0;
		font-size: 1.3rem;
		color: #f5c6c6;
	}

	.msg {
		margin: 0;
		font-size: 0.92rem;
		color: #aaa;
		white-space: pre-line; /* allows \n in message strings */
		line-height: 1.6;
	}

	.btn-lobby {
		margin-top: 0.4rem;
		background: #c0392b;
		border: none;
		color: #fff;
		padding: 0.55rem 1.8rem;
		border-radius: 7px;
		cursor: pointer;
		font-size: 1rem;
		font-weight: 600;
		transition: background 0.15s;
	}

	.btn-lobby:hover {
		background: #e74c3c;
	}
</style>
