import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { useAuth } from '../../auth/AuthContext'
import { errorText } from '../../lib/http'
import { Button, DataTable, Field, HashText, Loadable, READONLY_HINT, inputClass, useAsync, useToast } from '../../ui'
import { type TopoEdge, type TopoNode, type Topology, corrApi } from './api'

const UNITS = 'percent of floor plan (rough)'

function MapSvg({ nodes, edges, planUrl }: { nodes: TopoNode[]; edges: TopoEdge[]; planUrl: string | null }) {
  const placed = nodes.filter((n) => n.x != null && n.y != null)
  const by = new Map(placed.map((n) => [n.id, n]))
  const summary = `Camera map: ${nodes.length} camera nodes, ${edges.length} adjacency links${planUrl ? ' drawn over the uploaded floor plan' : ', no floor plan uploaded'}. ${placed.length} nodes have a position. The same information is in the tables below.`
  return (
    <div className="relative w-full max-w-3xl overflow-hidden rounded bg-navy-900" style={{ aspectRatio: '16 / 10' }}>
      {planUrl && <img src={planUrl} alt="Uploaded floor plan" className="absolute inset-0 h-full w-full object-fill" />}
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={summary} data-testid="camera-map" className="absolute inset-0 h-full w-full">
        {edges.map((e, i) => {
          const a = by.get(e.a)
          const b = by.get(e.b)
          return a && b ? <line key={i} x1={a.x!} y1={a.y!} x2={b.x!} y2={b.y!} stroke="#fb923c" strokeWidth={0.6} vectorEffect="non-scaling-stroke" /> : null
        })}
        {placed.map((n) => (
          <g key={n.id}>
            <circle cx={n.x!} cy={n.y!} r={1.6} fill="#ea580c" stroke="#fff" strokeWidth={0.3} vectorEffect="non-scaling-stroke" />
          </g>
        ))}
      </svg>
      {placed.map((n) => (
        <span key={n.id} aria-hidden="true" className="pointer-events-none absolute -translate-x-1/2 translate-y-1 rounded bg-navy-900/90 px-1 text-[11px] text-slate-100" style={{ left: `${n.x}%`, top: `${n.y}%` }}>
          {n.label || n.id}
        </span>
      ))}
    </div>
  )
}

function Editor({ caseId, topo, reload }: { caseId: number; topo: Topology; reload: () => void }) {
  const { can } = useAuth()
  const toast = useToast()
  const writable = can('case.write')
  const evidence = useAsync(() => api.listEvidence(caseId), [caseId])
  const [nodes, setNodes] = useState<TopoNode[]>(topo.nodes)
  const [edges, setEdges] = useState<TopoEdge[]>(topo.edges)
  const [nn, setNn] = useState({ id: '', label: '', evidence_id: '', channel: '', x: '', y: '' })
  const [ne, setNe] = useState({ a: '', b: '', max: '' })
  const [busy, setBusy] = useState(false)
  const [plan, setPlan] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const hash = topo.floorplan?.sha256

  useEffect(() => {
    let url: string | null = null
    let dead = false
    if (hash)
      corrApi.floorplanBlob(caseId).then((u) => {
        if (dead) {
          if (u) URL.revokeObjectURL(u)
        } else {
          url = u
          setPlan(u)
        }
      }).catch(() => setPlan(null))
    else setPlan(null)
    return () => {
      dead = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [caseId, hash])

  const dirty = JSON.stringify([nodes, edges]) !== JSON.stringify([topo.nodes, topo.edges])
  const addNode = () => {
    if (!nn.id.trim()) return toast.error('A node needs an id (letters, digits, . _ : -).')
    if (nodes.some((n) => n.id === nn.id.trim())) return toast.error(`Node id ${nn.id} is already used.`)
    setNodes([...nodes, { id: nn.id.trim(), label: nn.label, evidence_id: nn.evidence_id ? Number(nn.evidence_id) : null, channel: nn.channel !== '' ? Number(nn.channel) : null, x: nn.x !== '' ? Number(nn.x) : null, y: nn.y !== '' ? Number(nn.y) : null }])
    setNn({ id: '', label: '', evidence_id: '', channel: '', x: '', y: '' })
  }
  const addEdge = () => {
    if (!ne.a || !ne.b || ne.a === ne.b) return toast.error('Pick two different cameras.')
    if (edges.some((e) => (e.a === ne.a && e.b === ne.b) || (e.a === ne.b && e.b === ne.a))) return toast.error('That adjacency already exists.')
    setEdges([...edges, { a: ne.a, b: ne.b, max_transit_s: ne.max ? Number(ne.max) : null }])
    setNe({ a: '', b: '', max: '' })
  }
  const save = async () => {
    setBusy(true)
    try {
      await corrApi.putTopology(caseId, { nodes, edges, coordinate_units: UNITS, notes: topo.notes ?? '' })
      toast.ok('Camera layout saved (custody entry written).')
      reload()
    } catch (e) {
      toast.error(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const upload = async (f: File | undefined) => {
    if (!f) return
    try {
      await corrApi.uploadFloorplan(caseId, f)
      toast.ok('Floor plan stored with its SHA-256 (custody entry written).')
      reload()
    } catch (e) {
      toast.error(errorText(e))
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-300">
        The layout is what you tell the system: which recorder channel is which camera and which cameras are adjacent. Positions are rough, as a percentage of the floor plan, and are drawn but not used by the link rules.
      </p>
      <MapSvg nodes={nodes} edges={edges} planUrl={plan} />
      {topo.floorplan ? (
        <p className="text-xs text-slate-300">Floor plan {topo.floorplan.content_type}, {topo.floorplan.size_bytes} bytes, SHA-256 <HashText value={topo.floorplan.sha256} label="floor plan SHA-256" /></p>
      ) : (
        <p className="text-xs text-slate-300">No floor plan uploaded.</p>
      )}
      {writable && (
        <div className="flex flex-wrap items-center gap-2">
          <input ref={fileRef} type="file" accept="image/png,image/jpeg" aria-label="Floor plan image" onChange={(e) => upload(e.target.files?.[0])} className="text-sm" />
          <span className="text-xs text-slate-300">PNG or JPEG, at most 5 MiB.</span>
        </div>
      )}

      <section aria-labelledby="nodes-h" className="space-y-2">
        <h2 id="nodes-h" className="font-medium">Cameras</h2>
        <DataTable
          testId="nodes-table"
          caption="Camera nodes (table alternative to the map)"
          filterable={false}
          rows={nodes}
          rowKey={(n) => n.id}
          empty={{ title: 'No cameras defined', hint: writable ? 'Add the first camera below.' : 'An examiner defines the layout.' }}
          columns={[
            { key: 'id', header: 'Id', sort: (n) => n.id, render: (n) => n.id },
            { key: 'l', header: 'Label', render: (n) => n.label || '—' },
            { key: 'e', header: 'Evidence', render: (n) => (n.evidence_id != null ? `#${n.evidence_id}` : 'any') },
            { key: 'c', header: 'Channel', render: (n) => n.channel ?? '—' },
            { key: 'p', header: 'Position (%)', render: (n) => (n.x != null && n.y != null ? `${n.x}, ${n.y}` : 'not placed') },
            ...(writable ? [{ key: 'rm', header: 'Remove', render: (n: TopoNode) => <Button aria-label={`Remove camera ${n.id}`} onClick={() => { setNodes(nodes.filter((x) => x.id !== n.id)); setEdges(edges.filter((e) => e.a !== n.id && e.b !== n.id)) }}>Remove</Button> }] : []),
          ]}
        />
        {writable && (
          <div className="grid gap-2 md:grid-cols-6">
            <Field label="Id"><input aria-label="Camera id" className={inputClass} value={nn.id} onChange={(e) => setNn({ ...nn, id: e.target.value })} /></Field>
            <Field label="Label"><input aria-label="Camera label" className={inputClass} value={nn.label} onChange={(e) => setNn({ ...nn, label: e.target.value })} /></Field>
            <Field label="Evidence">
              <select aria-label="Camera evidence" className={inputClass} value={nn.evidence_id} onChange={(e) => setNn({ ...nn, evidence_id: e.target.value })}>
                <option value="">any evidence</option>
                {(evidence.data ?? []).map((e) => <option key={e.id} value={e.id}>#{e.id} {e.label}</option>)}
              </select>
            </Field>
            <Field label="Channel"><input aria-label="Camera channel" type="number" className={inputClass} value={nn.channel} onChange={(e) => setNn({ ...nn, channel: e.target.value })} /></Field>
            <Field label="X (%)"><input aria-label="Camera x" type="number" min={0} max={100} className={inputClass} value={nn.x} onChange={(e) => setNn({ ...nn, x: e.target.value })} /></Field>
            <Field label="Y (%)"><input aria-label="Camera y" type="number" min={0} max={100} className={inputClass} value={nn.y} onChange={(e) => setNn({ ...nn, y: e.target.value })} /></Field>
            <div><Button onClick={addNode}>Add camera</Button></div>
          </div>
        )}
      </section>

      <section aria-labelledby="edges-h" className="space-y-2">
        <h2 id="edges-h" className="font-medium">Adjacent cameras</h2>
        <DataTable
          testId="edges-table"
          caption="Camera adjacency"
          filterable={false}
          rows={edges}
          rowKey={(e) => `${e.a}-${e.b}`}
          empty={{ title: 'No adjacency defined', hint: 'Links need at least one pair of adjacent cameras.' }}
          columns={[
            { key: 'a', header: 'Camera A', render: (e) => e.a },
            { key: 'b', header: 'Camera B', render: (e) => e.b },
            { key: 't', header: 'Max transit (s)', render: (e) => e.max_transit_s ?? 'use the request window' },
            ...(writable ? [{ key: 'rm', header: 'Remove', render: (e: TopoEdge) => <Button aria-label={`Remove adjacency ${e.a} ${e.b}`} onClick={() => setEdges(edges.filter((x) => x !== e))}>Remove</Button> }] : []),
          ]}
        />
        {writable && (
          <div className="grid gap-2 md:grid-cols-4">
            <Field label="Camera A"><select aria-label="Adjacent A" className={inputClass} value={ne.a} onChange={(e) => setNe({ ...ne, a: e.target.value })}><option value="">choose</option>{nodes.map((n) => <option key={n.id}>{n.id}</option>)}</select></Field>
            <Field label="Camera B"><select aria-label="Adjacent B" className={inputClass} value={ne.b} onChange={(e) => setNe({ ...ne, b: e.target.value })}><option value="">choose</option>{nodes.map((n) => <option key={n.id}>{n.id}</option>)}</select></Field>
            <Field label="Max transit (s, optional)"><input aria-label="Max transit" type="number" min={1} className={inputClass} value={ne.max} onChange={(e) => setNe({ ...ne, max: e.target.value })} /></Field>
            <div className="flex items-end"><Button onClick={addEdge}>Add adjacency</Button></div>
          </div>
        )}
      </section>

      {writable ? (
        <Button variant="primary" busy={busy} disabled={!dirty} onClick={save}>Save camera layout</Button>
      ) : (
        <p className="text-sm text-slate-300">{READONLY_HINT}</p>
      )}
    </div>
  )
}

export function CameraMap({ caseId }: { caseId: number }) {
  const topo = useAsync(() => corrApi.topology(caseId), [caseId])
  return (
    <Loadable state={topo} rows={4}>
      {(t) =>
        // key on the stored version so a reload resets the draft to what the server holds
        <Editor key={`${t.updated_at ?? 'none'}-${t.floorplan?.sha256 ?? ''}`} caseId={caseId} topo={t} reload={topo.reload} />
      }
    </Loadable>
  )
}

