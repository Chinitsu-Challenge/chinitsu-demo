<script lang="ts">
	import { connect } from '$lib/ws';
	import { getUsername, logout } from '$lib/auth';

	interface Props {
		onLogout: () => void;
	}
	let { onLogout }: Props = $props();

	let roomName = $state('');
	let status = $state('');
	let connecting = $state(false);
	let vsBot = $state(false);
	let botLevel = $state('normal');

	const username = getUsername();

	async function handleConnect() {
		if (!roomName.trim()) {
			status = 'Please enter a room name.';
			return;
		}
		status = 'Connecting...';
		connecting = true;
		const result = await connect(roomName.trim(), { vsBot, botLevel });
		if (!result.ok) {
			// duplicate_id: +page.svelte switches to the dedicated waiting screen,
			// so we just clear the connecting state here — no error text needed.
			if (result.reason !== 'duplicate_id') {
				status = result.reason ?? 'Connection failed.';
			}
			connecting = false;
		}
	}

	function handleRoomKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleConnect();
	}

	function handleLogout() {
		logout();
		onLogout();
	}
</script>

<div id="lobby" class="screen">
	<div class="lobby-box">
		<h1>Chinitsu Showdown</h1>
		<p class="subtitle">清一色对战</p>
		<div class="user-info">
			<span>Logged in as <strong>{username}</strong></span>
			<button class="link-btn" onclick={handleLogout}>Logout</button>
		</div>
		<div class="form-group">
			<label for="input-room">Room Name</label>
			<input
				id="input-room"
				bind:value={roomName}
				onkeydown={handleRoomKeydown}
				placeholder="Room to join"
			/>
		</div>
		<div class="form-group bot-row">
			<label class="checkbox-label">
				<input type="checkbox" bind:checked={vsBot} />
				Play vs CPU
			</label>
			{#if vsBot}
				<select bind:value={botLevel} class="level-select">
					<option value="easy">Easy</option>
					<option value="normal">Normal</option>
					<option value="hard">Hard</option>
				</select>
			{/if}
		</div>
		<button class="btn btn-primary" disabled={connecting} onclick={handleConnect}>Connect</button>
		{#if status}
			<p class="status-msg">{status}</p>
		{/if}
	</div>
</div>

<style>
	.user-info {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.75rem;
		margin-bottom: 1rem;
		font-size: 0.95rem;
		color: #ccc;
	}
	.link-btn {
		background: none;
		border: none;
		color: #4fc3f7;
		cursor: pointer;
		font-size: 0.85rem;
		text-decoration: underline;
		padding: 0;
	}
	.link-btn:hover {
		color: #81d4fa;
	}
	.bot-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}
	.checkbox-label {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.9rem;
		color: #ccc;
		cursor: pointer;
		user-select: none;
	}
	.checkbox-label input[type='checkbox'] {
		width: 1rem;
		height: 1rem;
		cursor: pointer;
	}
	.level-select {
		background: #1e2a38;
		color: #e0e0e0;
		border: 1px solid #4fc3f7;
		border-radius: 4px;
		padding: 0.25rem 0.5rem;
		font-size: 0.85rem;
		cursor: pointer;
	}
</style>
