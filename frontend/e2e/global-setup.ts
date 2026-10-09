import { execFileSync } from 'node:child_process'
import { request } from '@playwright/test'
import { ensureDemo } from './seed'

// Builds the reference-data demo case once, after the web servers are up and before any spec runs
// (specs run in parallel workers, so they must only read it).
export default async function globalSetup() {
  // Demo accounts (clearly labelled demo users) in the e2e database; the app ships no default account.
  execFileSync('.venv/bin/python', ['-m', 'app.demo_data', 'seed-users'], {
    cwd: '../backend',
    env: { ...process.env, DATABASE_URL: process.env.E2E_DATABASE_URL ?? 'sqlite:///./e2e.db', NIRIKSHAN_DATA_DIR: './e2e-data', NIRIKSHAN_KEY_DIR: '../e2e-keys' },
    stdio: 'pipe',
  })
  const ctx = await request.newContext({ baseURL: `http://localhost:${process.env.WEB_PORT ?? 5183}` })
  await ensureDemo(ctx)
  await ctx.dispose()
}
