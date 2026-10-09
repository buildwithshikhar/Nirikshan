import { useState } from 'react'
import { Button, Card, EmptyState, ErrorState, Field, Skeleton, Unavailable, fmtBytes, inputClass, useAsync, useToast } from '../../ui'
import { type FileListing, intakeApi } from './api'

/** Step 1 of the wizard: choose the source on the SERVER (folder browser inside the evidence roots),
 * upload a file from this computer into the locked incoming folder, or type a path for a large image. */
export function SourcePicker({ caseId, value, onChange }: { caseId: number; value: string; onChange: (p: string) => void }) {
  const toast = useToast()
  const limits = useAsync(() => intakeApi.limits(), [])
  const [open, setOpen] = useState(false)
  const [dir, setDir] = useState('')
  const [typed, setTyped] = useState('')
  const listing = useAsync<FileListing | null>(() => (open ? intakeApi.list(dir) : Promise.resolve(null)), [open, dir])
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [uploaded, setUploaded] = useState<string>('')
  const max = limits.data?.max_bytes
  const tooBig = !!file && !!max && file.size > max

  const upload = async () => {
    if (!file) return
    setProgress(0)
    try {
      const r = await intakeApi.upload(caseId, file, setProgress)
      onChange(r.path)
      setUploaded(`Uploaded via browser: ${r.original_filename}, ${fmtBytes(r.size_bytes)}, SHA-256 ${r.sha256.slice(0, 16)}… (custody entry #${r.custody_seq}). The path below is filled in.`)
      toast.ok('Upload stored in the incoming folder and recorded in the custody log')
    } catch (e) {
      toast.error(e)
    } finally {
      setProgress(null)
    }
  }

  return (
    <div className="space-y-4">
      <Field label="Source path (server-side, inside the configured evidence roots)" hint="Type a path directly for very large images that already sit on the server, or pick one below.">
        <input className={inputClass} value={value} onChange={(e) => onChange(e.target.value)} />
      </Field>

      <Card title="Browse the server's evidence folders">
        {!open ? (
          <Button onClick={() => setOpen(true)}>Browse evidence folders</Button>
        ) : (
          <div className="space-y-3">
            <form
              className="flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                setDir(typed.trim())
              }}
            >
              <Field label="Open folder path">
                <input className={inputClass} value={typed} onChange={(e) => setTyped(e.target.value)} />
              </Field>
              <Button type="submit">Open</Button>
              {dir && <Button type="button" onClick={() => { setDir(listing.data?.parent ?? ''); setTyped('') }}>Up</Button>}
            </form>
            {listing.error ? (
              <ErrorState error={listing.error} onRetry={listing.reload} />
            ) : !listing.data ? (
              <Skeleton rows={3} />
            ) : listing.data.available === false ? (
              <Unavailable what="Folder browser" reason={listing.data.reason} />
            ) : listing.data.entries.length === 0 ? (
              <EmptyState title="This folder is empty" />
            ) : (
              <ul className="max-h-64 divide-y divide-navy-700 overflow-y-auto rounded bg-navy-900 text-sm" aria-label="Folder contents">
                {listing.data.entries.map((e) => (
                  <li key={e.path} className="flex items-center justify-between gap-3 px-3 py-1.5">
                    {e.kind === 'dir' ? (
                      <button className="text-left underline" onClick={() => { setDir(e.path); setTyped(e.path) }}>
                        {e.name}/
                      </button>
                    ) : (
                      <span>{e.name} <span className="text-xs text-slate-400">{fmtBytes(e.size ?? 0)}</span></span>
                    )}
                    {e.kind === 'file' && (
                      <Button aria-label={`Select ${e.name}`} onClick={() => { onChange(e.path); toast.info(`Selected ${e.name}`) }}>
                        Select
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {listing.data?.truncated && <p className="text-xs text-amber-300">Only the first 1000 entries are shown; type a more specific folder path.</p>}
            <p className="text-xs text-slate-400">Read-only: only folders inside the evidence roots are listed; links pointing outside them are hidden.</p>
          </div>
        )}
      </Card>

      <Card title="Upload a file from this computer">
        {limits.data && !limits.data.available ? (
          <Unavailable what="Browser upload" reason={limits.data.reason} />
        ) : (
          <div className="space-y-2">
            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">File to upload{max ? ` (up to ${fmtBytes(max)})` : ''}</span>
              <input type="file" aria-label="Upload a file from this computer" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setUploaded('') }} />
            </label>
            {tooBig && <p role="alert" className="text-sm text-red-300">This file is larger than the upload limit. Place it on the server and type its path instead.</p>}
            <Button disabled={!file || tooBig || progress !== null} busy={progress !== null} onClick={upload}>Upload to the incoming folder</Button>
            {progress !== null && <progress className="block w-64" value={progress} max={1} aria-label="Upload progress" />}
            {uploaded && <p role="status" data-testid="upload-result" className="text-sm text-emerald-300">{uploaded}</p>}
            <p className="text-xs text-slate-400">Stored under a generated name in a locked folder, hashed on arrival and recorded in the custody log with your user and the original filename. For very large images use the server path instead.</p>
          </div>
        )}
      </Card>
    </div>
  )
}
