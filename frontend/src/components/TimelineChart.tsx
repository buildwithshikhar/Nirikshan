import type { Gap, TimelineItem } from '../api_timeline'

const LANE_H = 34
const LEFT = 120
const WIDTH = 900
const PAD_TOP = 24

const ms = (s: string) => Date.parse(s)

function fmtAxis(t: number, spanMs: number) {
  const d = new Date(t)
  const iso = d.toISOString()
  return spanMs < 3_600_000 * 48 ? iso.slice(11, 19) + 'Z' : iso.slice(0, 16).replace('T', ' ') + 'Z'
}

/** SVG timeline: one lane per (evidence, channel). Dark bar = nominal start..end; light caps =
 * start/end uncertainty intervals (corrected when a drift model exists). Axis is UTC. */
export default function TimelineChart({
  items,
  gaps,
  onSelect,
  selected,
}: {
  items: TimelineItem[]
  gaps: Gap[]
  onSelect: (id: number) => void
  selected: number | null
}) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-slate-400" data-testid="chart-empty">
        Nothing can be placed on the axis yet. Items with an unknown timezone are listed below as
        unplaceable and are never drawn by default.
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
  const laneY = (it: { evidence_id: number; channel: number | null }) =>
    PAD_TOP + lanes.indexOf(`${it.evidence_id}:${it.channel ?? '-'}`) * LANE_H

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${WIDTH} ${H}`}
        className="w-full min-w-[640px] text-slate-300"
        role="img"
        aria-label="Timeline of clips with uncertainty bars, UTC axis"
        data-testid="timeline-svg"
      >
        {ticks.map((t, k) => (
          <g key={k}>
            <line x1={x(t)} x2={x(t)} y1={PAD_TOP - 6} y2={H - 6} stroke="#334155" strokeWidth={0.5} />
            <text x={x(t)} y={12} fontSize={10} textAnchor="middle" fill="currentColor">
              {fmtAxis(t, hi - lo)}
            </text>
          </g>
        ))}
        {lanes.map((l, k) => (
          <text key={l} x={4} y={PAD_TOP + k * LANE_H + 20} fontSize={11} fill="currentColor">
            ev {l.split(':')[0]} · ch {l.split(':')[1]}
          </text>
        ))}
        {gaps.map((g, k) => {
          const y = laneY(g)
          return (
            <rect
              key={k}
              x={x(ms(g.from))}
              width={Math.max(2, x(ms(g.to)) - x(ms(g.from)))}
              y={y + 4}
              height={LANE_H - 12}
              fill={g.certain ? '#7f1d1d' : '#78350f'}
              opacity={0.45}
              data-testid="gap-rect"
            >
              <title>{`gap ${g.gap_s_nominal.toFixed(1)} s (${g.certain ? 'certain' : 'possible'})`}</title>
            </rect>
          )
        })}
        {items.map((it) => {
          const y = laneY(it)
          const s = it.start!
          const e = it.end!
          const x0 = x((ms(s.lo) + ms(s.hi)) / 2)
          const x1 = x((ms(e.lo) + ms(e.hi)) / 2)
          const sel = selected === it.clip_id
          return (
            <g key={it.clip_id} onClick={() => onSelect(it.clip_id)} className="cursor-pointer" data-testid="timeline-bar">
              <rect x={x(ms(s.lo))} width={Math.max(3, x(ms(s.hi)) - x(ms(s.lo)))} y={y + 3} height={LANE_H - 10}
                fill="#fdba74" opacity={0.7} />
              <rect x={x(ms(e.lo))} width={Math.max(3, x(ms(e.hi)) - x(ms(e.lo)))} y={y + 3} height={LANE_H - 10}
                fill="#fdba74" opacity={0.7} />
              <rect x={x0} width={Math.max(2, x1 - x0)} y={y + 9} height={LANE_H - 22}
                fill={sel ? '#fb923c' : '#ea580c'} stroke={sel ? '#fff' : 'none'} />
              <title>{`clip ${it.clip_id}: ${s.lo} to ${e.hi}${it.flags.length ? ' [' + it.flags.join(', ') + ']' : ''}`}</title>
            </g>
          )
        })}
      </svg>
      <p className="text-xs text-slate-500">
        Dark bar: nominal start to end. Light caps: uncertainty of the start/end time (resolution, DST ambiguity,
        drift interval). Shaded: gaps (red = certain, amber = possible). Axis is UTC.
      </p>
    </div>
  )
}
