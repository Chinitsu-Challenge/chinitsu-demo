<script lang="ts">
	import Tile from './Tile.svelte';

	interface Props {
		count: number;
	}

	let { count }: Props = $props();
</script>

<div class="hand-row">
	{#each Array(count) as _, i (i)}
		<Tile back />
	{/each}
</div>
