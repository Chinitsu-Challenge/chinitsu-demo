<script lang="ts">
	import Tile from './Tile.svelte';

	interface Props {
		melds: string[][];
	}

	let { melds }: Props = $props();
</script>

<div class="fuuro-row">
	{#each melds as meld}
		<div class="meld-group">
			{#each meld as card}
				<Tile {card} />
			{/each}
		</div>
	{/each}
</div>
