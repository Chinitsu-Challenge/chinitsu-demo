<script lang="ts">
	import { logs } from '$lib/ws';

	let open = $state(false);
</script>

<div id="message-log">
	<div class="log-toggle" role="button" tabindex="0"
		onclick={() => (open = !open)}
		onkeydown={(e) => { if (e.key === 'Enter') open = !open; }}
	>
		Log {open ? '\u25BC' : '\u25B2'}
	</div>
	<div class="log-content" class:open>
		{#each $logs as entry}
			<div class="log-entry {entry.type}">{entry.text}</div>
		{/each}
	</div>
</div>
