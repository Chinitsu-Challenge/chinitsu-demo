<script lang="ts">
	import Tile from './Tile.svelte';

	interface Props {
		melds: string[][];
		tileRotation?: number;
	}

	let { melds, tileRotation = 0 }: Props = $props();

	// For a kan (4 tiles): indices 1 and 2 are face-down
	function isBack(meld: string[], idx: number): boolean {
		return meld.length === 4 && (idx === 1 || idx === 2);
	}
</script>

<div class="fuuro-group">
	{#each melds as meld}
		<div class="meld-group">
			{#each meld as card, idx}
				<Tile
					card={isBack(meld, idx) ? undefined : card}
					back={isBack(meld, idx)}
					rotation={isBack(meld, idx) ? 0 : tileRotation}
				/>
			{/each}
		</div>
	{/each}
</div>
