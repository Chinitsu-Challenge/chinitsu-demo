<script lang="ts">
	import Tile from './Tile.svelte';

	interface Props {
		melds: string[][];
		tileRotation?: number;
	}

	let { melds, tileRotation = 0 }: Props = $props();
</script>

<div class="fuuro-row">
	{#each melds as meld}
		<div class="meld-group">
			{#each meld as card}
				<Tile {card} rotation={tileRotation} />
			{/each}
		</div>
	{/each}
</div>
