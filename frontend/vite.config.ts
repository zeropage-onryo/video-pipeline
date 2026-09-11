import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

// The frontend is built and run on its own (`npm run dev`) and talks to
// the FastAPI app over the proxy below, so nothing here needs the Python
// server to be running until you actually wire a screen to real data.
// Point VITE_API_ORIGIN somewhere else to develop against a deployment.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    proxy: {
      // Google sign-in only works on localhost for this app (see
      // START_SERVER.md), which is the reason for a proxy rather than
      // CORS: the browser stays on one origin and the cookie keeps working.
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/refs': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/renders': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/characters': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/props': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/locations': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      // not under /api: the brand switch and sign-out are app/main.py and
      // app/auth.py routes, and both answer with a redirect
      '/brand': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/logout': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
})
