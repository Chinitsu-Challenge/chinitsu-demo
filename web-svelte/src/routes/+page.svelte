<script lang="ts">
	import { gameState } from '$lib/ws';
	import { isLoggedIn } from '$lib/auth';
	import Login from '$lib/components/Login.svelte';
	import Lobby from '$lib/components/Lobby.svelte';
	import Game from '$lib/components/Game.svelte';

	let phase = $derived($gameState.phase);
	let authed = $state(isLoggedIn());

	function onLoginSuccess() {
		authed = true;
	}
</script>

{#if !authed}
	<Login onSuccess={onLoginSuccess} />
{:else if phase === 'lobby'}
	<Lobby onLogout={() => (authed = false)} />
{:else}
	<Game />
{/if}
