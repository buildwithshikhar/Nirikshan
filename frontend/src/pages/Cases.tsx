import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { type Case, api } from '../api'
import Skeleton from '../components/Skeleton'

export default function Cases() {
  const [cases, setCases] = useState<Case[]>([])
  const [form, setForm] = useState({ case_number: '', title: '', description: '' })
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(() => {
    api.listCases().then(setCases).catch((e) => setError(e.message)).finally(() => setLoaded(true))
  }, [])
  useEffect(load, [load])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await api.createCase(form)
      setForm({ case_number: '', title: '', description: '' })
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const input = 'w-full rounded-md bg-navy-900 px-3 py-2 text-sm ring-1 ring-navy-700 focus:ring-accent'

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Cases</h1>
      <form onSubmit={create} className="grid gap-3 rounded-lg bg-navy-800 p-5 md:grid-cols-4">
        <input className={input} aria-label="Case number" placeholder="Case number" required value={form.case_number}
          onChange={(e) => setForm({ ...form, case_number: e.target.value })} />
        <input className={`${input} md:col-span-2`} aria-label="Title" placeholder="Title" required value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })} />
        <button className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-navy-900 hover:bg-accent-hover">
          Create case
        </button>
        <input className={`${input} md:col-span-4`} aria-label="Description" placeholder="Description (optional)" value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })} />
      </form>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      <section className="rounded-lg bg-navy-800 p-5">
        {!loaded ? (
          <Skeleton label="Loading cases" />
        ) : cases.length === 0 ? (
          <p className="text-sm text-slate-400">No cases yet. Create the first one with the form above.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Cases</caption>
            <thead className="text-slate-400">
              <tr><th scope="col" className="py-1">Number</th><th scope="col">Title</th><th scope="col">Examiner</th><th scope="col">Created (UTC)</th></tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id} className="border-t border-navy-700">
                  <td className="py-2"><Link className="text-accent hover:underline" to={`/cases/${c.id}`}>{c.case_number}</Link></td>
                  <td>{c.title}</td><td>{c.examiner}</td>
                  <td className="font-mono text-xs">{c.created_at.slice(0, 19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
