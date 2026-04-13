<script lang="ts">
	import { emotePopup } from '$lib/chat';

	let popup = $derived($emotePopup);
</script>

{#if popup}
	<div class="emote-popup" class:is-me={popup.isMe} class:is-opp={!popup.isMe}>
		<span class="emote-text">{popup.text}</span>
	</div>
{/if}

<style>
	.emote-popup {
		position: absolute;
		left: 50%;
		transform: translateX(-50%);
		pointer-events: none;
		z-index: 50;

		background: rgba(0, 0, 0, 0.75);
		color: #fff;
		border-radius: 1.2rem;
		padding: 0.5rem 1.1rem;
		font-size: 2rem;
		white-space: nowrap;
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);

		animation: emote-rise 2.5s ease forwards;
	}

	/* Opponent emote: anchored near the top zone */
	.emote-popup.is-opp {
		top: 12%;
	}

	/* My emote: anchored near the bottom zone */
	.emote-popup.is-me {
		bottom: 18%;
	}

	.emote-text {
		display: block;
		line-height: 1;
	}

	@keyframes emote-rise {
		0%   { opacity: 0; transform: translateX(-50%) translateY(8px) scale(0.6); }
		15%  { opacity: 1; transform: translateX(-50%) translateY(0)   scale(1.15); }
		25%  { opacity: 1; transform: translateX(-50%) translateY(0)   scale(1); }
		75%  { opacity: 1; transform: translateX(-50%) translateY(0)   scale(1); }
		100% { opacity: 0; transform: translateX(-50%) translateY(-8px) scale(0.9); }
	}
</style>
