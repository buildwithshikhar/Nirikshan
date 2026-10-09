import { type FormEvent, useState } from 'react'
import { type User } from '../../auth/api'
import { type Permission, ROLE_LABEL, type Role, roleCan } from '../../auth/permissions'
import { useCase } from '../../shell/CaseContext'
import { Button, Card, Chip, DataTable, EmptyState, Field, HashText, KV, Loadable, PageHeader, Tabs, fmtTime, inputClass, useAsync, useToast } from '../../ui'
import { adminApi } from './api'

const ROLES: Role[] = ['admin', 'examiner', 'reviewer', 'readonly']

function NewUser({ onDone }: { onDone: () => void }) {
  const toast = useToast()
  const [f, setF] = useState({ username: '', display_name: '', role: 'examiner' as Role, password: '' })
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      await adminApi.createUser(f)
      toast.ok(`User ${f.username} created`)
      setF({ username: '', display_name: '', role: 'examiner', password: '' })
      onDone()
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card title="Create a user">
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-2 xl:grid-cols-5 xl:items-end">
        <Field label="Username" hint="3-64 chars: a-z 0-9 . _ -"><input className={inputClass} required value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></Field>
        <Field label="Display name"><input className={inputClass} required value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></Field>
        <Field label="Role"><select className={inputClass} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></Field>
        <Field label="Initial password" hint="At least 12 characters"><input className={inputClass} type="password" autoComplete="new-password" required minLength={12} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        <Button type="submit" variant="primary" busy={busy}>Create user</Button>
      </form>
    </Card>
  )
}

function Users() {
  const toast = useToast()
  const users = useAsync(() => adminApi.users(), [])
  const act = (fn: () => Promise<unknown>, ok: string) => fn().then(() => (toast.ok(ok), users.reload())).catch(toast.error)
  const reset = (u: User) => {
    const pw = window.prompt(`New password for ${u.username} (at least 12 characters)`)
    if (pw) void act(() => adminApi.resetPassword(u.id, pw), `Password reset for ${u.username}; their sessions were revoked`)
  }
  return (
    <div className="space-y-4">
      <NewUser onDone={users.reload} />
      <Loadable state={users}>
        {(list) => (
          <DataTable
            caption="Users"
            rows={list}
            rowKey={(u) => u.id}
            empty={{ title: 'No users' }}
            columns={[
              { key: 'u', header: 'User', render: (u) => <><div className="font-medium">{u.display_name}</div><div className="text-xs text-slate-400">{u.username}</div></>, sort: (u) => u.username },
              { key: 'r', header: 'Role', render: (u) => (
                <select aria-label={`Role of ${u.username}`} className="rounded bg-navy-900 px-2 py-1 ring-1 ring-navy-600" value={u.role} onChange={(e) => void act(() => adminApi.patchUser(u.id, { role: e.target.value as Role }), `${u.username} is now ${ROLE_LABEL[e.target.value as Role]}`)}>
                  {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                </select>
              ), sort: (u) => u.role },
              { key: 's', header: 'State', render: (u) => <span className="flex gap-1">{u.active ? <Chip tone="ok">active</Chip> : <Chip tone="neutral">deactivated</Chip>}{u.locked && <Chip tone="bad">locked</Chip>}</span>, sort: (u) => String(u.active) },
              { key: 'l', header: 'Last login', render: (u) => fmtTime(u.last_login_at), sort: (u) => u.last_login_at },
              { key: 'a', header: 'Actions', render: (u) => (
                <span className="flex flex-wrap gap-1">
                  <Button onClick={() => void act(() => adminApi.patchUser(u.id, { active: !u.active }), `${u.username} ${u.active ? 'deactivated; sessions revoked' : 'reactivated'}`)}>{u.active ? 'Deactivate' : 'Reactivate'}</Button>
                  <Button onClick={() => reset(u)}>Reset password</Button>
                  {u.locked && <Button onClick={() => void act(() => adminApi.unlock(u.id), `${u.username} unlocked`)}>Unlock</Button>}
                </span>
              ) },
            ]}
          />
        )}
      </Loadable>
      <Members />
    </div>
  )
}

function Members() {
  const { caseId, cases } = useCase()
  const toast = useToast()
  const [sel, setSel] = useState<number | null>(caseId)
  const users = useAsync(() => adminApi.users(), [])
  const members = useAsync(() => (sel ? adminApi.members(sel) : Promise.resolve([])), [sel])
  const [add, setAdd] = useState('')
  const run = (fn: () => Promise<unknown>, ok: string) => fn().then(() => (toast.ok(ok), members.reload())).catch(toast.error)
  return (
    <Card title="Case membership (an admin sees case content only after being added; each change is a custody entry)">
      <label className="mb-3 flex items-center gap-2 text-sm">Case
        <select className="rounded bg-navy-900 px-2 py-1 ring-1 ring-navy-600" value={sel ?? ''} onChange={(e) => setSel(Number(e.target.value) || null)}>
          <option value="">Select…</option>
          {cases.map((c) => <option key={c.id} value={c.id}>{c.case_number}</option>)}
        </select>
      </label>
      {sel == null ? <EmptyState title="Select a case to manage its members" /> : (
        <Loadable state={members}>
          {(list) => (
            <>
              <DataTable
                caption="Case members"
                rows={list}
                rowKey={(m) => m.user_id}
                empty={{ title: 'No members' }}
                columns={[
                  { key: 'u', header: 'Member', render: (m) => `${m.display_name} (${m.username})`, sort: (m) => m.username },
                  { key: 'r', header: 'Role', render: (m) => ROLE_LABEL[m.role], sort: (m) => m.role },
                  { key: 'b', header: 'Added by', render: (m) => m.added_by },
                  { key: 'x', header: '', render: (m) => <Button variant="danger" onClick={() => run(() => adminApi.removeMember(sel, m.user_id), `${m.username} removed`)}>Remove</Button> },
                ]}
              />
              <div className="mt-3 flex items-end gap-2">
                <Field label="Add user to this case">
                  <select className={inputClass} value={add} onChange={(e) => setAdd(e.target.value)}>
                    <option value="">Select a user…</option>
                    {(users.data ?? []).filter((u) => u.active && !list.some((m) => m.user_id === u.id)).map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
                  </select>
                </Field>
                <Button disabled={!add} onClick={() => run(() => adminApi.addMember(sel, Number(add)), 'Member added')}>Add member</Button>
              </div>
            </>
          )}
        </Loadable>
      )}
    </Card>
  )
}

const PERMS: [Permission, string][] = [
  ['users.manage', 'Manage users and case membership'],
  ['case.create', 'Create a case'],
  ['case.write', 'Acquire, analyse, run jobs/analytics, set time assumptions, generate reports, build packages (case members)'],
  ['report.approve', 'Approve or reject a report (never your own)'],
  ['report.finalize', 'Finalise an approved report'],
  ['validation.rerun', 'Re-run the validation harness'],
]
function Roles() {
  return (
    <Card title="What each role can do (the server enforces these rules; the interface only hides what a role cannot do)">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Role permissions</caption>
          <thead className="text-xs uppercase text-slate-400"><tr><th scope="col" className="px-3 py-2">Capability</th>{ROLES.map((r) => <th key={r} scope="col" className="px-3 py-2">{ROLE_LABEL[r]}</th>)}</tr></thead>
          <tbody className="divide-y divide-navy-700">
            {PERMS.map(([p, label]) => (
              <tr key={p}><th scope="row" className="px-3 py-2 text-left font-normal">{label}</th>{ROLES.map((r) => <td key={r} className="px-3 py-2">{roleCan(r, p) ? <Chip tone="ok">yes</Chip> : <span className="text-slate-400">no</span>}</td>)}</tr>
            ))}
            <tr><th scope="row" className="px-3 py-2 text-left font-normal">Read case contents (members only; others get "not found")</th>{ROLES.map((r) => <td key={r} className="px-3 py-2"><Chip tone="ok">yes</Chip></td>)}</tr>
          </tbody>
        </table>
      </div>
    </Card>
  )
}

const fingerprint = async (hex: string) => {
  const bytes = Uint8Array.from(hex.match(/../g) ?? [], (h) => parseInt(h, 16))
  const d = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

function Keys() {
  const keys = useAsync(async () => {
    const [signing, pkg] = await Promise.all([adminApi.signingKey(), adminApi.packageKey()])
    const withFp = async (k: typeof signing) => ({ ...k, fingerprint: await fingerprint(k.public_key_hex).catch(() => '') })
    return [{ purpose: 'Custody log signing', ...(await withFp(signing)) }, { purpose: 'Evidence package signing', ...(await withFp(pkg)) }]
  }, [])
  return (
    <Loadable state={keys}>
      {(list) => (
        <div className="space-y-4">
          {list.map((k) => (
            <Card key={k.purpose} title={k.purpose}>
              <KV items={[['Algorithm', k.algorithm], ['Key id', <code key="i" className="font-mono">{k.key_id}</code>], ['Public key', <HashText key="p" value={k.public_key_hex} label={`${k.purpose} public key`} head={24} />], ['SHA-256 fingerprint of the public key', <HashText key="f" value={k.fingerprint} label="fingerprint" head={24} />]]} />
            </Card>
          ))}
          <p className="text-sm text-slate-400">Read-only: private keys never leave the server. Whether a key is passphrase-protected at rest is shown by <code>python -m app.cli key-status</code> on the host (not exposed over the API). Key rotation is deferred (see docs/ROUND_D_DEFERRED.md).</p>
        </div>
      )}
    </Loadable>
  )
}

function Config() {
  const s = useAsync(async () => ({ sys: await adminApi.system(), audit: await adminApi.audit() }), [])
  return (
    <Loadable state={s}>
      {({ sys, audit }) => (
        <div className="space-y-4">
          <Card title="Configuration (read-only)">
            <KV items={[['Tool version', sys.tool_version], ['Database schema version', String(sys.schema_version)], ['Mode', sys.mode], ['Clock NTP sync', sys.ntp_status], ['Evidence roots', sys.evidence_roots.join(', ') || 'none configured'], ['Block devices allowed', sys.block_devices_allowed ? 'yes' : 'no'], ['ffmpeg', sys.ffmpeg.available ? (sys.ffmpeg.version ?? 'available') : 'not installed (degraded mode)']]} />
          </Card>
          <Card title="Audit trail (latest 200 API requests)">
            <DataTable
              caption="Audit trail"
              rows={audit}
              rowKey={(a) => a.id}
              empty={{ title: 'No audit rows' }}
              pageSize={15}
              columns={[
                { key: 't', header: 'Time (UTC)', render: (a) => fmtTime(a.timestamp_utc), sort: (a) => a.timestamp_utc },
                { key: 'u', header: 'Principal', render: (a) => a.examiner || '(anonymous)', sort: (a) => a.examiner },
                { key: 'm', header: 'Method', render: (a) => a.method, sort: (a) => a.method },
                { key: 'p', header: 'Path', render: (a) => <code className="text-xs">{a.path}</code>, sort: (a) => a.path },
                { key: 's', header: 'Status', render: (a) => <Chip tone={a.status_code < 400 ? 'ok' : 'bad'}>{a.status_code}</Chip>, sort: (a) => a.status_code },
              ]}
            />
          </Card>
        </div>
      )}
    </Loadable>
  )
}

export default function AdminModule() {
  return (
    <div>
      <PageHeader title="Admin" subtitle="Users, roles, keys and configuration. Local accounts only; every change is audited." />
      <Tabs label="Admin sections" tabs={[
        { id: 'users', label: 'Users', render: () => <Users /> },
        { id: 'roles', label: 'Roles', render: () => <Roles /> },
        { id: 'keys', label: 'Keys', render: () => <Keys /> },
        { id: 'config', label: 'Config and audit', render: () => <Config /> },
      ]} />
    </div>
  )
}
