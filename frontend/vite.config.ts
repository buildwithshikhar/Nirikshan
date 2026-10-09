import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // the Help module bundles ../docs/*.md (offline, rendered in-app)
    fs: { allow: ['..'] },
    proxy: {
      '/api': proxyTarget,
      '/health': proxyTarget,
    },
  },
})
