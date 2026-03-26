import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/ws': {
				target: 'ws://localhost:8000',
				ws: true
			},
			'/assets': {
				target: 'http://localhost:8000'
			},
			'/api': {
				target: 'http://localhost:8000'
			}
		}
	}
});
