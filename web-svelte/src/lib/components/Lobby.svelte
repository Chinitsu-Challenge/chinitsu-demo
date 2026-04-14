<script lang="ts">
	import { connect, type RoomSettings } from '$lib/ws';
	import { getUsername, logout } from '$lib/auth';

	interface Props {
		onLogout: () => void;
	}
	let { onLogout }: Props = $props();

	let roomName = $state('');
	let status = $state('');
	let connecting = $state(false);

	// Room settings
	let initialPoint = $state(150000);
	let noAgariPunishment = $state(20000);
	let sortHand = $state(false);
	let debugCode = $state('');

	const username = getUsername();

	const pointPresets = [50000, 100000, 150000, 200000];
	const punishPresets = [10000, 20000, 30000];

	function fmt(n: number) {
		return (n / 1000).toFixed(0) + 'k';
	}

	async function handleConnect() {
		if (!roomName.trim()) {
			status = 'Please enter a room name.';
			return;
		}
		status = 'Connecting...';
		connecting = true;

		const settings: RoomSettings = {
			initialPoint,
			noAgariPunishment,
			sortHand,
		};
		const code = parseInt(debugCode, 10);
		if (!isNaN(code) && code > 100) settings.debugCode = code;

		const result = await connect(roomName.trim(), settings);
		if (!result.ok) {
			status = result.reason ?? 'Connection failed.';
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
				placeholder="Room to join or create"
			/>
		</div>

		<div class="settings-section">
			<div class="settings-title">Room Settings <span class="settings-hint">(host only)</span></div>

			<div class="setting-row">
				<span class="setting-label">模式 Mode</span>
				<div class="preset-group">
					<button
						class="preset-btn"
						class:active={!sortHand}
						onclick={() => (sortHand = false)}
					>正常 Normal</button>
					<button
						class="preset-btn"
						class:active={sortHand}
						onclick={() => (sortHand = true)}
					>简单 Easy</button>
				</div>
			</div>

			<div class="setting-row">
				<span class="setting-label">起始点数 Starting Points</span>
				<div class="preset-group">
					{#each pointPresets as p}
						<button
							class="preset-btn"
							class:active={initialPoint === p}
							onclick={() => (initialPoint = p)}
						>{fmt(p)}</button>
					{/each}
				</div>
			</div>

			<div class="setting-row">
				<span class="setting-label">惩罚点数 Penalty</span>
				<div class="preset-group">
					{#each punishPresets as p}
						<button
							class="preset-btn"
							class:active={noAgariPunishment === p}
							onclick={() => (noAgariPunishment = p)}
						>{fmt(p)}</button>
					{/each}
				</div>
			</div>

			<div class="setting-row">
				<label for="input-cheat">作弊码 Cheat Code</label>
				<input
					id="input-cheat"
					class="cheat-input"
					type="number"
					bind:value={debugCode}
					placeholder="Optional (e.g. 114514)"
				/>
			</div>
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

	.settings-section {
		border: 1px solid #333;
		border-radius: 8px;
		padding: 0.85rem 1rem;
		margin-bottom: 1rem;
		background: rgba(255, 255, 255, 0.03);
	}
	.settings-title {
		font-size: 0.8rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #aaa;
		margin-bottom: 0.75rem;
	}
	.settings-hint {
		font-weight: 400;
		color: #666;
		text-transform: none;
		letter-spacing: 0;
	}
	.setting-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin-bottom: 0.6rem;
	}
	.setting-row:last-child {
		margin-bottom: 0;
	}
	.setting-label {
		width: 11rem;
		font-size: 0.85rem;
		color: #ccc;
		flex-shrink: 0;
	}
	.preset-group {
		display: flex;
		gap: 0.35rem;
	}
	.preset-btn {
		padding: 0.25rem 0.6rem;
		border: 1px solid #444;
		border-radius: 4px;
		background: transparent;
		color: #bbb;
		cursor: pointer;
		font-size: 0.85rem;
		transition: border-color 0.15s, color 0.15s, background 0.15s;
	}
	.preset-btn:hover {
		border-color: #4fc3f7;
		color: #fff;
	}
	.preset-btn.active {
		border-color: #4fc3f7;
		background: rgba(79, 195, 247, 0.15);
		color: #4fc3f7;
		font-weight: 600;
	}
	.cheat-input {
		width: 10rem;
		padding: 0.25rem 0.5rem;
		border: 1px solid #444;
		border-radius: 4px;
		background: #1a1a1a;
		color: #ccc;
		font-size: 0.85rem;
	}
	.cheat-input:focus {
		outline: none;
		border-color: #4fc3f7;
	}
	/* hide number input arrows */
	.cheat-input::-webkit-outer-spin-button,
	.cheat-input::-webkit-inner-spin-button {
		-webkit-appearance: none;
	}
	.cheat-input[type='number'] {
		appearance: textfield;
		-moz-appearance: textfield;
	}
</style>
