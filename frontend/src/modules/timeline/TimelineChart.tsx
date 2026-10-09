import { useState } from 'react'
import { Button, DataTable } from '../../ui'
import type { Gap, TimelineItem } from './api'

const LANE_H = 34
const LEFT = 120
const WIDTH = 900
const PAD_TOP = 24
const ms = (s: string) => Date.parse(s)

function fmtAxis(t: number, spanMs: number) {
  const iso = new Date(t).toISOString()
  return spanMs < 3_600_000 * 48 ? iso.slice(11, 19) + 'Z' : iso.slice(0, 16).replace('T', ' ') + 'Z'
}

/** Uncertainty-bar chart: one lane per (evidence, channel). Light caps are the start/end uncertainty
 * intervals, the dark bar is nominal start..end. The SVG is an image with a text summary; every clip
 * is reachable (keyboard included) from the table alternative, which the toggle switches to. */
export default function TimelineChart({
  items,
  gaps,
  onSelect,
}: {
  items: TimelineItem[]
  gaps: Gap[]
  onSelect: (id: number) => void
}) {
  const [asTable, setAsTable] = useState(false)
  if (items.length === 0) {
    return (
      <p className="text-sm text-slate-300" data-testid="chart-empty">
        Nothing can be placed on the axis yet. Clips whose evidence has no timezone assumption are listed under Unplaceable clips and are never drawn by default.
      </p>
    )
  }
  const lanes = Array.from(new Set(items.map((i) => `${i.evidence_id}:${i.channel ?? '-'}`))).sort()
  let lo = Math.min(...items.map((i) => ms(i.start!.lo)))
  let hi = Math.max(...items.map((i) => ms(i.end!.hi)))
  if (hi - lo < 1000) hi = lo + 1000
  const span = hi - lo
  lo -= span * 0.02
  hi += span * 0.02
  const x = (t: number) => LEFT + ((t - lo) / (hi - lo)) * (WIDTH - LEFT - 10)
  const H = PAD_TOP + lanes.length * LANE_H + 10
  const ticks = Array.from({ length: 6 }, (_, k) => lo + ((hi - lo) * k) / 5)
  const laneY = (it: { evidence_id: number; channel: number | null }) => PAD_TOP + lanes.indexOf(`${it.evidence_id}:${it.channel ?? '-'}`) * LANE_H
  const summary = `Timeline chart, UTC axis from ${new Date(lo).toISOString()} to ${new Date(hi).toISOString()}: ${items.length} placed clips in ${lanes.length} lanes, ${gaps.length} gaps. Light caps show start and end time uncertainty. A table with the same data is available.`

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <Button onClick={() => setAsTable(!asTable)} aria-pressed={asTable} data-testid="chart-toggle">
          {asTable ? 'Show chart' : 'Show as table'}
        </Button>
      </div>
      {asTable ? (
        <DataTable
          testId="chart-table"
          caption="Placed clips (table alternative to the timeline chart)"
          rows={items}
          rowKey={(i) => i.clip_id}
          onRowClick={(i) => onSelect(i.clip_id)}
          columns={[
            {
              key: 'clip',
              header: 'Clip',
              sort: (i) => i.clip_id,
              render: (i) => <button className="text-accent underline" onClick={(e) => { e.stopPropagation(); onSelect(i.clip_id) }}>Clip {i.clip_id}</button>,
            },
            { key: 'ev', header: 'Evidence', sort: (i) => i.evidence_id, render: (i) => i.evidence_id },
            { key: 'ch', header: 'Channel', sort: (i) => i.channel ?? -1, render: (i) => i.channel ?? 'n/a' },
            { key: 'start', header: 'Start (UTC, interval)', sort: (i) => i.start!.lo, render: (i) => <span className="font-mono text-xs">{i.start!.lo} to {i.start!.hi}</span> },
            { key: 'end', header: 'End (UTC, interval)', sort: (i) => i.end!.lo, render: (i) => <span className="font-mono text-xs">{i.end!.lo} to {i.end!.hi}</span> },
            { key: 'flags', header: 'Flags', render: (i) => (i.flags.length ? i.flags.join(', ') : 'none'), text: (i) => i.flags.join(' ') },
          ]}
        />
      ) : (
        <div className="overflow-x-auto">
          <svg viewBox={`0 0 ${WIDTH} ${H}`} className="w-full min-w-[640px] text-slate-300" role="img" aria-label={summary} data-testid="timeline-svg">
            {ticks.map((t, k) => (
              <g key={k}>
                <line x1={x(t)} x2={x(t)} y1={PAD_TOP - 6} y2={H - 6} stroke="#334155" strokeWidth={0.5} />
                <text x={x(t)} y={12} fontSize={10} textAnchor="middle" fill="currentColor">{fmtAxis(t, hi - lo)}</text>
              </g>
            ))}
            {lanes.map((l, k) => (
              <text key={l} x={4} y={PAD_TOP + k * LANE_H + 20} fontSize={11} fill="currentColor">ev {l.split(':')[0]} · ch {l.split(':')[1]}</text>
            ))}
            {gaps.map((g, k) => (
              <rect key={k} x={x(ms(g.from))} width={Math.max(2, x(ms(g.to)) - x(ms(g.from)))} y={laneY(g) + 4} height={LANE_H - 12} fill={g.certain ? '#b91c1c' : '#b45309'} opacity={0.5} data-testid="gap-rect" />
            ))}
            {items.map((it) => {
              const y = laneY(it)
              const s = it.start!
              const e = it.end!
              const x0 = x((ms(s.lo) + ms(s.hi)) / 2)
              const x1 = x((ms(e.lo) + ms(e.hi)) / 2)
              return (
                <g key={it.clip_id} onClick={() => onSelect(it.clip_id)} className="cursor-pointer" data-testid="timeline-bar">
                  <rect x={x(ms(s.lo))} width={Math.max(3, x(ms(s.hi)) - x(ms(s.lo)))} y={y + 3} height={LANE_H - 10} fill="#fdba74" opacity={0.8} />
                  <rect x={x(ms(e.lo))} width={Math.max(3, x(ms(e.hi)) - x(ms(e.lo)))} y={y + 3} height={LANE_H - 10} fill="#fdba74" opacity={0.8} />
                  <rect x={x0} width={Math.max(2, x1 - x0)} y={y + 9} height={LANE_H - 22} fill="#ea580c" />
                </g>
              )
            })}
          </svg>
        </div>
      )}
      <p className="mt-2 text-xs text-slate-300">
        Dark bar: nominal start to end. Light caps: uncertainty of the start/end time (resolution, DST ambiguity, drift interval). Shaded: gaps (red = certain,
        amber = possible). Axis is UTC. Click a bar, or use the table, for details.
      </p>
    </div>
  )
}
