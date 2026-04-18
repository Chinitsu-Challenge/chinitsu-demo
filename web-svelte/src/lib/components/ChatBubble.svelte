<script lang="ts">
	import { chatBubble } from '$lib/chat';

	let bubble = $derived($chatBubble);
</script>

{#if bubble}
	{#key bubble.seq}
		<div class="chat-bubble" class:is-me={bubble.isMe} class:is-opp={!bubble.isMe}>
			<div class="bubble-body">{bubble.text}</div>
		</div>
	{/key}
{/if}

<style>
	.chat-bubble {
		position: absolute;
		left: 50%;
		transform: translateX(-50%);
		pointer-events: none;
		z-index: 51;
	}

	.chat-bubble.is-opp {
		top: 9%;
	}

	.chat-bubble.is-me {
		bottom: 22%;
	}

	.bubble-body {
		position: relative;
		background: rgba(255, 255, 255, 0.88);
		color: #1a1a1a;
		backdrop-filter: blur(4px);
		font-size: 0.95rem;
		line-height: 1.35;
		padding: 10px 14px;
		border-radius: 14px;
		max-width: 260px;
		min-width: 48px;
		text-align: center;
		word-break: break-word;
		white-space: pre-wrap;
		box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
		border: 2px solid rgba(0, 0, 0, 0.15);
	}

	/* Tail */
	.bubble-body::before,
	.bubble-body::after {
		content: '';
		position: absolute;
		left: 50%;
		width: 0;
		height: 0;
		border-style: solid;
	}

	.is-me .bubble-body::before {
		bottom: -12px;
		transform: translateX(-50%);
		border-width: 12px 10px 0 10px;
		border-color: rgba(0, 0, 0, 0.15) transparent transparent transparent;
	}
	.is-me .bubble-body::after {
		bottom: -9px;
		transform: translateX(-50%);
		border-width: 10px 8px 0 8px;
		border-color: #fff transparent transparent transparent;
	}

	.is-opp .bubble-body::before {
		top: -12px;
		transform: translateX(-50%);
		border-width: 0 10px 12px 10px;
		border-color: transparent transparent rgba(0, 0, 0, 0.15) transparent;
	}
	.is-opp .bubble-body::after {
		top: -9px;
		transform: translateX(-50%);
		border-width: 0 8px 10px 8px;
		border-color: transparent transparent #fff transparent;
	}

	.chat-bubble.is-me .bubble-body {
		animation: bubble-pop-up 4s ease forwards;
	}
	.chat-bubble.is-opp .bubble-body {
		animation: bubble-pop-down 4s ease forwards;
	}

	@keyframes bubble-pop-up {
		0%   { opacity: 0; transform: scale(0.6) translateY(20px); }
		6%   { opacity: 1; transform: scale(1.05) translateY(0); }
		12%  { transform: scale(1) translateY(0); }
		88%  { opacity: 1; transform: scale(1) translateY(0); }
		100% { opacity: 0; transform: scale(0.95) translateY(-6px); }
	}

	@keyframes bubble-pop-down {
		0%   { opacity: 0; transform: scale(0.6) translateY(-20px); }
		6%   { opacity: 1; transform: scale(1.05) translateY(0); }
		12%  { transform: scale(1) translateY(0); }
		88%  { opacity: 1; transform: scale(1) translateY(0); }
		100% { opacity: 0; transform: scale(0.95) translateY(6px); }
	}
</style>
