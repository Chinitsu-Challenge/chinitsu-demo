<script lang="ts">
	import { connect } from '$lib/ws';

	let playerName = $state('');
	let roomName = $state('');
	let status = $state('');
	let connecting = $state(false);

	async function handleConnect() {
		if (!playerName.trim() || !roomName.trim()) {
			status = 'Please enter both fields.';
			return;
		}
		status = 'Connecting...';
		connecting = true;
		const result = await connect(playerName.trim(), roomName.trim());
		if (!result.ok) {
			status = result.reason ?? 'Connection failed.';
			connecting = false;
		}
		// on success, gameState.phase changes to 'waiting' and the parent switches view
	}

	function handleRoomKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleConnect();
	}

	function handlePlayerKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			const el = document.getElementById('input-room');
			el?.focus();
		}
	}
</script>

<div id="lobby" class="screen">
	<div class="lobby-box">
		<h1>Chinitsu Showdown</h1>
		<p class="subtitle">清一色对战</p>
		<div class="form-group">
			<label for="input-player">Player Name</label>
			<input id="input-player" bind:value={playerName} onkeydown={handlePlayerKeydown} placeholder="Your name" />
		</div>
		<div class="form-group">
			<label for="input-room">Room Name</label>
			<input id="input-room" bind:value={roomName} onkeydown={handleRoomKeydown} placeholder="Room to join" />
		</div>
		<button class="btn btn-primary" disabled={connecting} onclick={handleConnect}>Connect</button>
		{#if status}
			<p class="status-msg">{status}</p>
		{/if}
	</div>
</div>
