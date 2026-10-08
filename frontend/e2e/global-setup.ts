import { request } from '@playwright/test'
import { ensureDemo } from './seed'

// Builds the SYNTHETIC demo case once, after the web servers are up and before any spec runs
// (specs run in parallel workers, so they must only read it).
export default async function globalSetup() {
  const ctx = await request.newContext({ baseURL: `http://localhost:${process.env.WEB_PORT ?? 5183}` })
  await ensureDemo(ctx)
  await ctx.dispose()
}
