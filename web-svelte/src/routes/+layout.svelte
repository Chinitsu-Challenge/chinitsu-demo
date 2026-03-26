<script lang="ts">
	import '../app.css';
	let { children } = $props();
</script>

<svelte:head>
	<title>Chinitsu Showdown</title>
</svelte:head>

{@render children()}
