<script lang="ts">
	import { emotePopup, EMOTES } from '$lib/chat';

	let popup = $derived($emotePopup);
	let emoteDef = $derived(popup ? EMOTES[popup.emoteId] : null);
</script>

{#if popup && emoteDef}
	<div class="emote-popup" class:is-me={popup.isMe} class:is-opp={!popup.isMe}>
		<img src={emoteDef.src} alt={emoteDef.label} class="emote-img" />
	</div>
{/if}

<style>
	.emote-popup {
		position: absolute;
		left: 50%;
		transform: translateX(-50%);
		pointer-events: none;
		z-index: 50;
	}

	/* Opponent emote: anchored near the top zone */
	.emote-popup.is-opp {
		top: 12%;
	}

	/* My emote: anchored near the bottom zone */
	.emote-popup.is-me {
		bottom: 18%;
	}

	.emote-img {
		display: block;
		width: 120px;
		height: 120px;
		border-radius: 1rem;
		box-shadow: 0 6px 24px rgba(0, 0, 0, 0.5);
	}

	/* Emote shoots out from player position */
	.emote-popup.is-me .emote-img {
		animation: shoot-up 2.5s ease forwards;
	}
	.emote-popup.is-opp .emote-img {
		animation: shoot-down 2.5s ease forwards;
	}

	@keyframes shoot-up {
		0%   { opacity: 0; transform: scale(0.2) translateY(80px); }
		12%  { opacity: 1; transform: scale(1.15) translateY(0); }
		20%  { opacity: 1; transform: scale(1) translateY(0); }
		75%  { opacity: 1; transform: scale(1) translateY(0); }
		100% { opacity: 0; transform: scale(0.95) translateY(-10px); }
	}

	@keyframes shoot-down {
		0%   { opacity: 0; transform: scale(0.2) translateY(-80px); }
		12%  { opacity: 1; transform: scale(1.15) translateY(0); }
		20%  { opacity: 1; transform: scale(1) translateY(0); }
		75%  { opacity: 1; transform: scale(1) translateY(0); }
		100% { opacity: 0; transform: scale(0.95) translateY(10px); }
	}
</style>
