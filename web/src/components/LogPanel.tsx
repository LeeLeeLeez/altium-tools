import { useEffect, useRef } from 'react'
import { Button } from 'oink-ui'

interface Props {
  lines: string[]
  onClear?: () => void
}

/** 日志面板 —— 对应旧版的 tk.Text 日志区。 */
export default function LogPanel({ lines, onClear }: Props) {
  const ref = useRef<HTMLPreElement>(null)

  useEffect(() => {
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  return (
    <div className="logpanel">
      <div className="logpanel__bar">
        <span className="logpanel__count">{lines.length} 行</span>
        <span style={{ flex: '1 1 auto' }} />
        {onClear && (
          <Button size="sm" variant="ghost" onClick={onClear}>
            清空日志
          </Button>
        )}
      </div>
      <pre className="log ok-scroll" ref={ref}>
        {lines.join('\n')}
      </pre>
    </div>
  )
}
