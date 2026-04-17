<script lang="ts">
	import { onDestroy } from 'svelte';
	import { errorToast } from '$lib/ws';

	let toast = $derived($errorToast);

	const DISMISS_MS = 4_000;
	let timer: ReturnType<typeof setTimeout> | null = null;

	// Start auto-dismiss whenever a new toast appears (keyed by id)
	$effect(() => {
		if (toast) {
			if (timer !== null) clearTimeout(timer);
			timer = setTimeout(() => {
				errorToast.set(null);
				timer = null;
			}, DISMISS_MS);
		}
	});

	function dismiss() {
		if (timer !== null) { clearTimeout(timer); timer = null; }
		errorToast.set(null);
	}

	onDestroy(() => {
		if (timer !== null) clearTimeout(timer);
	});
</script>

{#if toast}
	<div class="toast" role="status" aria-live="polite">
		<span class="toast-msg">{toast.message}</span>
		<button class="toast-close" onclick={dismiss} aria-label="关闭">✕</button>
	</div>
{/if}

<style>
	.toast {
		position: fixed;
		bottom: 5.5rem;   /* above the action bar */
		left: 50%;
		transform: translateX(-50%);
		z-index: 400;
		background: #2a1a1a;
		border: 1px solid #c0392b;
		border-left: 4px solid #e74c3c;
		border-radius: 8px;
		padding: 0.65rem 1rem 0.65rem 1.1rem;
		display: flex;
		align-items: center;
		gap: 0.75rem;
		min-width: 220px;
		max-width: 380px;
		box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
		animation: slide-up 0.2s ease;
	}

	@keyframes slide-up {
		from { opacity: 0; transform: translateX(-50%) translateY(10px); }
		to   { opacity: 1; transform: translateX(-50%) translateY(0); }
	}

	.toast-msg {
		flex: 1;
		font-size: 0.9rem;
		color: #f5c6c6;
		line-height: 1.4;
	}

	.toast-close {
		background: transparent;
		border: none;
		color: #888;
		cursor: pointer;
		font-size: 0.85rem;
		padding: 0.1rem 0.2rem;
		line-height: 1;
		transition: color 0.15s;
		flex-shrink: 0;
	}

	.toast-close:hover {
		color: #ccc;
	}
</style>
