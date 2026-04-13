<script lang="ts">
	import { onMount } from 'svelte';
	import { gameState, connect, isSpectator } from '$lib/ws';
	import { isLoggedIn, getToken } from '$lib/auth';
	import Login from '$lib/components/Login.svelte';
	import Lobby from '$lib/components/Lobby.svelte';
	import Game from '$lib/components/Game.svelte';
	import SpectatorGame from '$lib/components/SpectatorGame.svelte';

	let phase = $derived($gameState.phase);
	let authed = $state(isLoggedIn());
	let autoConnecting = $state(false);

	async function tryAutoReconnect() {
		if (!isLoggedIn()) return;
		try {
			const res = await fetch('/api/active_room', {
				headers: { Authorization: `Bearer ${getToken()}` }
			});
			if (!res.ok) return;
			const data = await res.json();
			if (data.room_name) {
				autoConnecting = true;
				await connect(data.room_name);
			}
		} catch {
			// network error — fall back to lobby
		} finally {
			autoConnecting = false;
		}
	}

	function onLoginSuccess() {
		authed = true;
		tryAutoReconnect();
	}

	onMount(() => {
		if (authed) tryAutoReconnect();
	});
</script>

{#if !authed}
	<Login onSuccess={onLoginSuccess} />
{:else if autoConnecting}
	<div class="screen reconnecting">
		<p>Reconnecting...</p>
	</div>
{:else if phase === 'lobby'}
	<Lobby onLogout={() => (authed = false)} />
{:else if $isSpectator}
	<SpectatorGame />
{:else}
	<Game />
{/if}

<style>
	.reconnecting {
		display: flex;
		align-items: center;
		justify-content: center;
		color: #aaa;
		font-size: 1.1rem;
	}
</style>
