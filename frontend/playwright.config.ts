import { defineConfig } from '@playwright/test'

const API_PORT = 8010
const WEB_PORT = 5183
const backendDb = process.env.E2E_DATABASE_URL ?? 'sqlite:///./e2e.db'

// Starts its own backend (needs backend/.venv) and Vite dev server.
export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  reporter: 'list',
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: 'retain-on-failure' },
  webServer: [
    {
      command: `.venv/bin/uvicorn app.main:app --port ${API_PORT}`,
      cwd: '../backend',
      url: `http://localhost:${API_PORT}/health`,
      env: {
        DATABASE_URL: backendDb,
        CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
      },
      reuseExistingServer: false,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { VITE_PROXY_TARGET: `http://localhost:${API_PORT}` },
      reuseExistingServer: false,
    },
  ],
})
