<script lang="ts">
	import { onMount } from 'svelte';
	import { gameState, connect, isSpectator, duplicateTab } from '$lib/ws';
	import { isLoggedIn, getToken } from '$lib/auth';
	import Login from '$lib/components/Login.svelte';
	import Lobby from '$lib/components/Lobby.svelte';
	import Game from '$lib/components/Game.svelte';
	import SpectatorGame from '$lib/components/SpectatorGame.svelte';

	let phase = $derived($gameState.phase);
	let authed = $state(isLoggedIn());
	let autoConnecting = $state(false);

	async function tryAutoReconnect() {
		if (!isLoggedIn()) return;
		try {
			const res = await fetch('/api/active_room', {
				headers: { Authorization: `Bearer ${getToken()}` }
			});
			if (!res.ok) return;
			const data = await res.json();
			if (data.room_name) {
				autoConnecting = true;
				await connect(data.room_name);
			}
		} catch {
			// network error — fall back to lobby
		} finally {
			autoConnecting = false;
		}
	}

	function onLoginSuccess() {
		authed = true;
		tryAutoReconnect();
	}

	onMount(() => {
		if (authed) tryAutoReconnect();
	});
</script>

{#if !authed}
	<Login onSuccess={onLoginSuccess} />
{:else if autoConnecting}
	<div class="screen center-screen">
		<p>Reconnecting...</p>
	</div>
{:else if $duplicateTab}
	<div class="screen center-screen duplicate-tab">
		<div class="duplicate-box">
			<div class="duplicate-icon">⚠</div>
			<h2>已在其他窗口登录</h2>
			<p>你的账号正在另一个标签页中进行游戏。</p>
			<p class="hint">关闭那个标签页后，此页面将自动接入游戏。</p>
			<div class="waiting-dots">
				<span></span><span></span><span></span>
			</div>
		</div>
	</div>
{:else if phase === 'lobby'}
	<Lobby onLogout={() => (authed = false)} />
{:else if $isSpectator}
	<SpectatorGame />
{:else}
	<Game />
{/if}

<style>
	.center-screen {
		display: flex;
		align-items: center;
		justify-content: center;
		color: #aaa;
		font-size: 1.1rem;
	}

	.duplicate-tab {
		background: #1a1a2e;
		min-height: 100vh;
	}

	.duplicate-box {
		text-align: center;
		padding: 2.5rem 3rem;
		background: #16213e;
		border-radius: 12px;
		border: 1px solid #2a2a4e;
		max-width: 400px;
	}

	.duplicate-icon {
		font-size: 2.5rem;
		margin-bottom: 1rem;
		color: #f0a500;
	}

	.duplicate-box h2 {
		color: #e0e0e0;
		margin: 0 0 0.75rem;
		font-size: 1.2rem;
	}

	.duplicate-box p {
		color: #aaa;
		margin: 0.25rem 0;
		font-size: 0.95rem;
		line-height: 1.5;
	}

	.duplicate-box .hint {
		color: #4ecca3;
		margin-top: 0.75rem;
		font-size: 0.88rem;
	}

	.waiting-dots {
		display: flex;
		justify-content: center;
		gap: 6px;
		margin-top: 1.5rem;
	}

	.waiting-dots span {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: #4fc3f7;
		animation: blink 1.2s infinite;
	}

	.waiting-dots span:nth-child(2) { animation-delay: 0.2s; }
	.waiting-dots span:nth-child(3) { animation-delay: 0.4s; }

	@keyframes blink {
		0%, 80%, 100% { opacity: 0.2; }
		40% { opacity: 1; }
	}
</style>
