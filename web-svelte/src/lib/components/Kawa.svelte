<script lang="ts">
	import Tile from './Tile.svelte';
	import type { KawaEntry } from '$lib/types';

	interface Props {
		kawa: KawaEntry[];
		tileRotation?: number;
	}

	let { kawa, tileRotation = 0 }: Props = $props();

	let rows = $derived(
		Array.from({ length: Math.ceil(kawa.length / 5) }, (_, i) => kawa.slice(i * 5, i * 5 + 5))
	);
</script>

<div class="kawa-section">
	<div class="kawa">
		{#each rows as row, rowIdx}
			<div class="kawa-row">
				{#each row as entry, j}
					<Tile
						card={entry.card}
						riichi={entry.isRiichi}
						rotation={entry.isRiichi ? tileRotation + 1 : tileRotation}
						lastDiscard={rowIdx * 5 + j === kawa.length - 1}
					/>
				{/each}
			</div>
		{/each}
	</div>
</div>
