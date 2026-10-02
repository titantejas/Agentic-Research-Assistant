import { defineConfig } from 'vite';
export default defineConfig({ server: { port: 5173, proxy: { '/chat': 'http://localhost:8000' } } });
