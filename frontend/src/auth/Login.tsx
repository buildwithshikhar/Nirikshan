import { type FormEvent, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../lib/http'
import { Button, Field, inputClass } from '../ui'
import { useAuth } from './AuthContext'

export default function Login() {
  const { login, status, notice } = useAuth()
  const nav = useNavigate()
  const [sp] = useSearchParams()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (status === 'ready') {
    queueMicrotask(() => nav(sp.get('next') || '/', { replace: true }))
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(username, password)
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 429
          ? 'Too many attempts. Wait a few minutes before trying again.'
          : err instanceof ApiError && err.status === 401
            ? 'Sign-in failed: wrong username or password, or the account is locked or deactivated.'
            : `Sign-in failed: ${err instanceof Error ? err.message : String(err)}`,
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-navy-900 p-6">
      <main id="main" className="w-full max-w-md rounded-xl bg-navy-800 p-8 shadow-xl">
        <div className="text-3xl font-bold text-accent">Nirikshan</div>
        <h1 className="mt-1 text-lg text-slate-200">Sign in</h1>
        <p className="mt-1 text-xs text-slate-400">DVR/NVR forensic recovery workbench. Local accounts only.</p>
        {notice && (
          <p role="status" data-testid="login-notice" className="mt-4 rounded bg-navy-700 p-2 text-sm">
            {notice}
          </p>
        )}
        <form onSubmit={submit} className="mt-5 space-y-4">
          <Field label="Username">
            <input className={inputClass} autoComplete="username" autoFocus required value={username} onChange={(e) => setUsername(e.target.value)} />
          </Field>
          <Field label="Password">
            <input className={inputClass} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          {error && (
            <p role="alert" data-testid="login-error" className="rounded border border-red-400 bg-red-950 p-2 text-sm text-red-100">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" busy={busy} className="w-full">
            Sign in
          </Button>
        </form>
      </main>
    </div>
  )
}
