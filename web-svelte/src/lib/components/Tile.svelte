<script lang="ts">
	interface Props {
		card?: string | null;
		back?: boolean;
		rotation?: number;
		riichi?: boolean;
		tsumo?: boolean;
		selected?: boolean;
		lastDiscard?: boolean;
		onclick?: () => void;
	}

	let {
		card = null,
		back = false,
		rotation = 0,
		riichi = false,
		tsumo = false,
		selected = false,
		lastDiscard = false,
		onclick
	}: Props = $props();

	let src = $derived(
		back ? `/assets/back_${rotation}.png` : `/assets/${card}_${rotation}.png`
	);
	let alt = $derived(back ? 'back' : card ?? '');
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div
	class="tile"
	class:tile-back={back}
	class:riichi-discard={riichi}
	class:tsumo-tile={tsumo}
	class:selected
	class:last-discard={lastDiscard}
	class:clickable={!!onclick}
	role={onclick ? 'button' : undefined}
	tabindex={onclick ? 0 : undefined}
	onclick={onclick}
	onkeydown={(e) => { if (onclick && (e.key === 'Enter' || e.key === ' ')) onclick(); }}
>
	<img {src} {alt} draggable="false" />
</div>
