<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { playerLeftNotif } from '$lib/ws';

	let notif = $derived($playerLeftNotif);

	const AUTO_DISMISS_MS = 10_000;
	let timer: ReturnType<typeof setTimeout> | null = null;

	function dismiss() {
		if (timer !== null) { clearTimeout(timer); timer = null; }
		playerLeftNotif.set(null);
	}

	// Start auto-dismiss whenever a new notif appears
	$effect(() => {
		if (notif) {
			if (timer !== null) clearTimeout(timer);
			timer = setTimeout(dismiss, AUTO_DISMISS_MS);
		}
	});

	onDestroy(() => {
		if (timer !== null) clearTimeout(timer);
	});
</script>

{#if notif}
	<div class="notif-wrap" role="status" aria-live="polite">
		<div class="notif-box">
			<p class="notif-msg">
				<span class="notif-name">{notif.displayName}</span> 已离开房间
			</p>
			<p class="notif-sub">Waiting for a new player to join…</p>
			<button class="btn-ok" onclick={dismiss}>确认</button>
		</div>
	</div>
{/if}

<style>
	.notif-wrap {
		position: fixed;
		/* Right side, clear of the center panel */
		bottom: 6rem;
		right: 1.5rem;
		z-index: 250;
		pointer-events: none; /* allow clicks through the backdrop */
	}

	.notif-box {
		pointer-events: all;
		background: #1a2332;
		border: 1px solid #334;
		border-left: 3px solid #f0a500;
		border-radius: 10px;
		padding: 1rem 1.25rem;
		min-width: 220px;
		max-width: 280px;
		box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45);
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		animation: slide-in 0.25s ease;
	}

	@keyframes slide-in {
		from { opacity: 0; transform: translateX(20px); }
		to   { opacity: 1; transform: translateX(0); }
	}

	.notif-msg {
		margin: 0;
		font-size: 0.95rem;
		color: #dde;
		line-height: 1.4;
	}

	.notif-name {
		font-weight: 600;
		color: #f0c060;
	}

	.notif-sub {
		margin: 0;
		font-size: 0.78rem;
		color: #778;
	}

	.btn-ok {
		align-self: flex-end;
		background: transparent;
		border: 1px solid #445;
		color: #99a;
		padding: 0.3rem 0.9rem;
		border-radius: 5px;
		cursor: pointer;
		font-size: 0.85rem;
		transition: border-color 0.15s, color 0.15s;
	}

	.btn-ok:hover {
		border-color: #aab;
		color: #ccd;
	}
</style>
