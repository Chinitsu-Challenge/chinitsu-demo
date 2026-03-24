<script lang="ts">
	import { gameState } from '$lib/ws';
	import Lobby from '$lib/components/Lobby.svelte';
	import Game from '$lib/components/Game.svelte';

	let phase = $derived($gameState.phase);
</script>

{#if phase === 'lobby'}
	<Lobby />
{:else}
	<Game />
{/if}
