<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { gameState } from '$lib/ws';

	const TOTAL = 10;
	const RADIUS = 22;
	const CIRCUMFERENCE = 2 * Math.PI * RADIUS; // ≈ 138.23

	let count = $state(TOTAL);
	let timer: ReturnType<typeof setInterval> | null = null;

	function returnToLobby() {
		cleanup();
		gameState.update((s) => ({ ...s, phase: 'lobby' }));
	}

	function cleanup() {
		if (timer !== null) {
			clearInterval(timer);
			timer = null;
		}
	}

	onMount(() => {
		timer = setInterval(() => {
			count--;
			if (count <= 0) {
				returnToLobby();
			}
		}, 1000);
	});

	onDestroy(cleanup);

	// stroke-dashoffset 从 0（满圆）线性增加到 CIRCUMFERENCE（空圆）
	let dashOffset = $derived(CIRCUMFERENCE * (1 - count / TOTAL));
</script>

<div class="dissolved-backdrop">
	<div class="dissolved-box" role="alertdialog" aria-live="assertive">
		<p class="dissolved-title">房主已解散房间</p>
		<p class="dissolved-sub">Host dissolved the room</p>

		<div class="ring-wrap">
			<svg class="ring-svg" viewBox="0 0 52 52" aria-hidden="true">
				<!-- track ring -->
				<circle cx="26" cy="26" r={RADIUS} fill="none" stroke="#2a3a50" stroke-width="4" />
				<!-- progress ring (rotated so it starts from the top) -->
				<circle
					cx="26"
					cy="26"
					r={RADIUS}
					fill="none"
					stroke="#4a9eff"
					stroke-width="4"
					stroke-linecap="round"
					stroke-dasharray={CIRCUMFERENCE}
					stroke-dashoffset={dashOffset}
					style="transform: rotate(-90deg); transform-origin: 26px 26px; transition: stroke-dashoffset 0.9s linear;"
				/>
			</svg>
			<span class="ring-number">{count}</span>
		</div>

		<button class="btn-exit" onclick={returnToLobby}>退出</button>
	</div>
</div>

<style>
	.dissolved-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.65);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 300;
	}

	.dissolved-box {
		background: #1a2332;
		border: 1px solid #334;
		border-radius: 14px;
		padding: 2rem 2.5rem;
		min-width: 260px;
		text-align: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1.1rem;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
	}

	.dissolved-title {
		margin: 0;
		font-size: 1.15rem;
		font-weight: 600;
		color: #e0e0e0;
	}

	.dissolved-sub {
		margin: -0.6rem 0 0;
		font-size: 0.8rem;
		color: #667;
	}

	/* Ring wrapper: SVG + number layered via position */
	.ring-wrap {
		position: relative;
		width: 64px;
		height: 64px;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.ring-svg {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
	}

	.ring-number {
		position: relative;
		font-size: 1.35rem;
		font-weight: 700;
		color: #c8d8f0;
		font-variant-numeric: tabular-nums;
	}

	.btn-exit {
		background: transparent;
		border: 1px solid #4a9eff;
		color: #4a9eff;
		padding: 0.45rem 1.4rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.95rem;
		transition: background 0.15s, color 0.15s;
	}

	.btn-exit:hover {
		background: #4a9eff22;
		color: #78b8ff;
	}
</style>
