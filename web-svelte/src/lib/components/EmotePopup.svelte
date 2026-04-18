<script lang="ts">
	import { emotePopups, EMOTES } from '$lib/chat';

	let popups = $derived($emotePopups);

	// Deterministic small horizontal offset per popup id so stacked emotes don't perfectly overlap.
	function offsetFor(id: number): number {
		const slots = [0, -60, 60, -110, 110, -30, 30];
		return slots[id % slots.length];
	}
</script>

{#each popups as p (p.id)}
	{@const def = EMOTES[p.emoteId]}
	{#if def}
		<div
			class="emote-popup"
			class:is-me={p.isMe}
			class:is-opp={!p.isMe}
			style="--dx: {offsetFor(p.id)}px; z-index: {50 + p.id};"
		>
			<img src={def.src} alt={def.label} class="emote-img" />
		</div>
	{/if}
{/each}

<style>
	.emote-popup {
		position: absolute;
		left: calc(50% + var(--dx, 0px));
		transform: translateX(-50%);
		pointer-events: none;
	}

	/* Opponent emote: anchored near the top zone */
	.emote-popup.is-opp {
		top: 10%;
	}

	/* My emote: anchored near the bottom zone */
	.emote-popup.is-me {
		bottom: 20%;
	}

	.emote-img {
		display: block;
		width: 150px;
		height: 150px;
		border-radius: 0;
		box-shadow: none;
	}

	.emote-popup.is-me .emote-img {
		animation: shoot-up 3s ease forwards;
	}
	.emote-popup.is-opp .emote-img {
		animation: shoot-down 3s ease forwards;
	}

	@keyframes shoot-up {
		0%   { opacity: 0; transform: scale(0.3) translateY(60px); }
		10%  { opacity: 1; transform: scale(1.15) translateY(0); }
		18%  { opacity: 1; transform: scale(1) translateY(0); }
		85%  { opacity: 1; transform: scale(1) translateY(0); }
		100% { opacity: 0; transform: scale(0.95) translateY(-10px); }
	}

	@keyframes shoot-down {
		0%   { opacity: 0; transform: scale(0.3) translateY(-60px); }
		10%  { opacity: 1; transform: scale(1.15) translateY(0); }
		18%  { opacity: 1; transform: scale(1) translateY(0); }
		85%  { opacity: 1; transform: scale(1) translateY(0); }
		100% { opacity: 0; transform: scale(0.95) translateY(10px); }
	}
</style>
