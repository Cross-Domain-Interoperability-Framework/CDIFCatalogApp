import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// API_URL is the server as seen from where Vite runs:
// http://localhost:8000 on a developer machine, http://api:8000 under Docker Compose.
export default defineConfig({
  plugins: [react()],
  server: {
    // /catalog and /records are the server's public addresses: the DCAT feed and the record pages.
    proxy: Object.fromEntries(
      ['/api', '/catalog', '/records'].map((path) => [path, process.env.API_URL || 'http://localhost:8000']),
    ),
    // File-change events do not cross a Docker bind mount on Windows, so Compose asks for polling.
    watch: process.env.WATCH_POLL ? { usePolling: true, interval: 500 } : undefined,
  },
});
