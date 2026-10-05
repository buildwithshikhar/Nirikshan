import { tmpdir } from 'node:os'
import { realpathSync, rmSync } from 'node:fs'
import { defineConfig } from '@playwright/test'

const API_PORT = 8010
const WEB_PORT = 5183
// Fresh e2e database and workspace each run (there are no schema migrations yet).
// (the config is evaluated again inside workers: only the main process may clean up)
if (process.env.TEST_WORKER_INDEX === undefined) {
  rmSync('../backend/e2e.db', { force: true })
  rmSync('../backend/e2e-data', { recursive: true, force: true })
}

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
        NIRIKSHAN_EVIDENCE_ROOTS: realpathSync(tmpdir()),
        NIRIKSHAN_DATA_DIR: './e2e-data',
        NIRIKSHAN_KEY_DIR: '../e2e-keys',
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
