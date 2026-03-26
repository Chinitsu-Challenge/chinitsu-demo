<script lang="ts">
	import Tile from './Tile.svelte';

	interface Props {
		tiles: string[];
		interactive?: boolean;
		selectedIdx?: number | null;
		turnStage?: string | null;
		onselect?: (idx: number) => void;
	}

	let { tiles, interactive = false, selectedIdx = null, turnStage = null, onselect }: Props = $props();

	function isTsumo(idx: number): boolean {
		return interactive && idx === tiles.length - 1 && tiles.length % 3 === 2 && turnStage === 'after_draw';
	}
</script>

<div class="hand-row my-hand-row">
	{#each tiles as card, idx (idx)}
		<Tile
			{card}
			tsumo={isTsumo(idx)}
			selected={selectedIdx === idx}
			onclick={interactive ? () => onselect?.(idx) : undefined}
		/>
	{/each}
</div>
