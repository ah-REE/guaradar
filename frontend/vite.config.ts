import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Backend target for local development.
 *
 * The frontend calls same-origin `/api/...` by default and Vite proxies it to the FastAPI
 * server. Two reasons this is better than a hardcoded `http://127.0.0.1:8000` in the client:
 *
 *  1. No CORS in local dev. `localhost` and `127.0.0.1` are different origins, so a
 *     hardcoded absolute URL depends on the backend's CORS list matching exactly what the
 *     browser sent. A proxy removes the cross-origin hop entirely.
 *  2. One place to change. If the backend port moves, only this file changes.
 *
 * Override with `VITE_API_PROXY_TARGET` (e.g. a remote dev API) or point the client at an
 * absolute URL via `VITE_API_BASE_URL`. No secrets are involved; this is a local HTTP target.
 */
const BACKEND_TARGET = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000'

const proxy = {
  '/api': {
    target: BACKEND_TARGET,
    changeOrigin: true,
    // The API is read-only; no websocket upgrade is needed.
  },
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy,
  },
  // `vite preview` serves the production build; it needs the same proxy so a built bundle
  // works locally without a real reverse proxy in front.
  preview: {
    port: 4173,
    proxy,
  },
  build: {
    target: 'es2022',
    sourcemap: false,
  },
})
