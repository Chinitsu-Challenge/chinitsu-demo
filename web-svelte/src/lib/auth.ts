const TOKEN_KEY = 'chinitsu_token';
const UUID_KEY = 'chinitsu_uuid';
const USERNAME_KEY = 'chinitsu_username';

export function getToken(): string {
	return localStorage.getItem(TOKEN_KEY) ?? '';
}

export function getUuid(): string {
	return localStorage.getItem(UUID_KEY) ?? '';
}

export function getUsername(): string {
	return localStorage.getItem(USERNAME_KEY) ?? '';
}

export function isLoggedIn(): boolean {
	return !!getToken();
}

export function logout() {
	localStorage.removeItem(TOKEN_KEY);
	localStorage.removeItem(UUID_KEY);
	localStorage.removeItem(USERNAME_KEY);
}

function saveAuth(data: { access_token: string; uuid: string; username: string }) {
	localStorage.setItem(TOKEN_KEY, data.access_token);
	localStorage.setItem(UUID_KEY, data.uuid);
	localStorage.setItem(USERNAME_KEY, data.username);
}

export async function register(
	username: string,
	password: string
): Promise<{ ok: boolean; error?: string }> {
	try {
		const res = await fetch('/api/register', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ username, password })
		});
		if (!res.ok) {
			const body = await res.json();
			return { ok: false, error: body.detail ?? 'Registration failed' };
		}
		const data = await res.json();
		saveAuth(data);
		return { ok: true };
	} catch {
		return { ok: false, error: 'Network error' };
	}
}

export async function login(
	username: string,
	password: string
): Promise<{ ok: boolean; error?: string }> {
	try {
		const res = await fetch('/api/login', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ username, password })
		});
		if (!res.ok) {
			const body = await res.json();
			return { ok: false, error: body.detail ?? 'Login failed' };
		}
		const data = await res.json();
		saveAuth(data);
		return { ok: true };
	} catch {
		return { ok: false, error: 'Network error' };
	}
}
