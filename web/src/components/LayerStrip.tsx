import type { StripItem } from '../types'

interface Props {
  strip: StripItem[]
}

/** 层序色带 —— 横排在层序表上方，一眼看出每层的类型与配色。 */
export default function LayerStrip({ strip }: Props) {
  if (!strip.length) return null
  // 块多了放不下文字（每块约 1/层数 宽）
  const showText = strip.length <= 40
  return (
    <div className="strip" role="img" aria-label="层序色带">
      {strip.map((s) => (
        <div
          key={s.index}
          className="strip__item"
          style={{ background: s.color }}
          title={`#${s.index} ${s.type} · 绕组 ${s.label || '—'}`}
        >
          {showText ? `${s.index}${s.type}` : s.index}
        </div>
      ))}
    </div>
  )
}
