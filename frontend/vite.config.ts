import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/sessions': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/session': {
        target: 'ws://localhost:8080',
        ws: true,
      },
      '/interview-adk': {
        target: 'ws://localhost:8080',
        ws: true,
      },
      '/api/report': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ''),
      },
      '/run-code': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
});
