import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy API requests to the FastAPI backend.
      // Assumes backend runs on http://localhost:8000 by default.
      // Keep empty proxy config since we call the Render backend directly.
      // (We leave the object keys out to avoid accidental calls to localhost.)

    },
  },
});

