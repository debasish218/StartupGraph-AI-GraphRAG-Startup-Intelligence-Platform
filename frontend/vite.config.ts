import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const target = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000';
const proxy = {
  '/api': { target, changeOrigin: true },
  '/health': { target, changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
  build: { chunkSizeWarningLimit: 1500 },
});
