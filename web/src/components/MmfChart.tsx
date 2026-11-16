import { useMemo } from 'react'
import { EmptyState } from 'oink-ui'

import type { MmfSeries } from '../types'

interface Props {
  series: MmfSeries[]
}

const W = 640
const H = 210
const PAD = { l: 38, r: 12, t: 12, b: 22 }
const COLORS = ['var(--ok-accent)', 'var(--ok-info)', 'var(--ok-success)', 'var(--ok-warning)']

/** MMF 磁动势分布 —— 纵轴=层序（顶→底），横轴=安匝。 */
export default function MmfChart({ series }: Props) {
  const model = useMemo(() => {
    const values = series.flatMap((s) => s.mmfAfter ?? [])
    if (!values.length) return null
    const min = Math.min(0, ...values)
    const max = Math.max(0, ...values)
    const span = max - min || 1
    const n = Math.max(...series.map((s) => (s.mmfAfter?.length ?? 0)), 1)
    const x = (i: number) => PAD.l + (i / Math.max(1, n - 1)) * (W - PAD.l - PAD.r)
    const y = (v: number) => PAD.t + (1 - (v - min) / span) * (H - PAD.t - PAD.b)
    return { min, max, span, n, x, y }
  }, [series])

  if (!model) {
    return (
      <EmptyState
        size="sm"
        title="暂无 MMF 数据"
        description="先在左侧调好叠层参数并重建序列。"
      />
    )
  }

  const ticks = [model.max, (model.max + model.min) / 2, model.min]

  return (
    <svg
      className="mmf"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="MMF 磁动势分布"
    >
      {ticks.map((t, i) => (
        <g key={i}>
          <line
            className={i === 1 ? 'mmf__zero' : 'mmf__grid'}
            x1={PAD.l}
            x2={W - PAD.r}
            y1={model.y(t)}
            y2={model.y(t)}
          />
          <text className="mmf__label" x={4} y={model.y(t) + 3}>
            {t.toFixed(1)}
          </text>
        </g>
      ))}
      <line
        className="mmf__axis"
        x1={PAD.l}
        x2={PAD.l}
        y1={PAD.t}
        y2={H - PAD.b}
      />
      <line
        className="mmf__axis"
        x1={PAD.l}
        x2={W - PAD.r}
        y1={H - PAD.b}
        y2={H - PAD.b}
      />
      {series.map((s, si) => (
        <polyline
          key={si}
          fill="none"
          stroke={COLORS[si % COLORS.length]}
          strokeWidth={1.8}
          strokeLinejoin="round"
          strokeLinecap="round"
          points={(s.mmfAfter ?? [])
            .map((v, i) => `${model.x(i).toFixed(1)},${model.y(v).toFixed(1)}`)
            .join(' ')}
        />
      ))}
      <text className="mmf__label" x={PAD.l} y={H - 6}>
        顶
      </text>
      <text className="mmf__label" x={W - PAD.r - 10} y={H - 6}>
        底
      </text>
      <text className="mmf__label" x={W - PAD.r - 60} y={PAD.t + 10}>
        {series.length} 个状态
      </text>
    </svg>
  )
}
