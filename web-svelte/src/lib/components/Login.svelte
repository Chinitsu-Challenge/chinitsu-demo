<script lang="ts">
	import { login, register } from '$lib/auth';

	let mode: 'login' | 'register' = $state('login');
	let username = $state('');
	let password = $state('');
	let status = $state('');
	let loading = $state(false);

	interface Props {
		onSuccess: () => void;
	}
	let { onSuccess }: Props = $props();

	async function handleSubmit() {
		if (!username.trim() || !password.trim()) {
			status = 'Please enter both fields.';
			return;
		}
		loading = true;
		status = '';

		const result =
			mode === 'login'
				? await login(username.trim(), password.trim())
				: await register(username.trim(), password.trim());

		if (result.ok) {
			onSuccess();
		} else {
			status = result.error ?? 'Something went wrong.';
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleSubmit();
	}

	function toggleMode() {
		mode = mode === 'login' ? 'register' : 'login';
		status = '';
	}
</script>

<div id="lobby" class="screen">
	<div class="lobby-box">
		<h1>Chinitsu Showdown</h1>
		<p class="subtitle">清一色对战喵</p>
		<h2 class="auth-title">{mode === 'login' ? 'Login' : 'Register'}</h2>
		<div class="form-group">
			<label for="input-username">Username</label>
			<input
				id="input-username"
				bind:value={username}
				onkeydown={handleKeydown}
				placeholder="Username"
				maxlength="20"
			/>
		</div>
		<div class="form-group">
			<label for="input-password">Password</label>
			<input
				id="input-password"
				type="password"
				bind:value={password}
				onkeydown={handleKeydown}
				placeholder="Password"
			/>
		</div>
		<button class="btn btn-primary" disabled={loading} onclick={handleSubmit}>
			{mode === 'login' ? 'Login' : 'Register'}
		</button>
		{#if status}
			<p class="status-msg">{status}</p>
		{/if}
		<p class="toggle-link">
			{mode === 'login' ? "Don't have an account?" : 'Already have an account?'}
			<button class="link-btn" onclick={toggleMode}>
				{mode === 'login' ? 'Register' : 'Login'}
			</button>
		</p>
	</div>
</div>

<style>
	.auth-title {
		margin: 0 0 1rem;
		font-size: 1.2rem;
		font-weight: 600;
	}
	.toggle-link {
		margin-top: 1rem;
		font-size: 0.9rem;
		color: #888;
	}
	.link-btn {
		background: none;
		border: none;
		color: #4fc3f7;
		cursor: pointer;
		font-size: 0.9rem;
		text-decoration: underline;
		padding: 0;
	}
	.link-btn:hover {
		color: #81d4fa;
	}
</style>
