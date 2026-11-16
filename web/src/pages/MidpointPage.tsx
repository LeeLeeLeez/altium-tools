import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Grid,
  Input,
  Page,
  PageHeader,
  Select,
  Switch,
  Tabs,
  Text,
  toast,
} from 'oink-ui'

import { api, errText } from '../api'
import LogPanel from '../components/LogPanel'
import type { MidpointMeta, PageProps } from '../types'

interface PanelProps {
  orient: 'v' | 'h'
  setStatus: (s: string) => void
  setStatusError: (s: string) => void
}

export default function MidpointPage(props: PageProps) {
  const [tab, setTab] = useState('v')
  return (
    <Page size="full">
      <PageHeader
        title="画中点短线"
        description="选中两条同向的线 → 读取 → 在中点画一条短线。"
      />
      <Tabs
        label="方向"
        value={tab}
        onChange={(v) => setTab(v)}
        items={[
          {
            value: 'v',
            label: '画竖直短线',
            content: <MidpointPanel orient="v" setStatus={props.setStatus}
              setStatusError={props.setStatusError} />,
          },
          {
            value: 'h',
            label: '画水平短线',
            content: <MidpointPanel orient="h" setStatus={props.setStatus}
              setStatusError={props.setStatusError} />,
          },
        ]}
      />
    </Page>
  )
}

function MidpointPanel({ orient, setStatus, setStatusError }: PanelProps) {
  const [meta, setMeta] = useState<MidpointMeta | null>(null)
  const [start, setStart] = useState('6337.0')
  const [len, setLen] = useState('39')
  const [width, setWidth] = useState('4')
  const [layer, setLayer] = useState('')
  const [force, setForce] = useState(false)
  const [tracks, setTracks] = useState<string[]>([])
  const [log, setLog] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const spec = meta?.specs[orient]
  const keySig = spec ? spec.keys.join(',') : ''

  // ---------------------------------------------------------- 读配置
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const [m, c] = await Promise.all([
          api.get<{ meta: MidpointMeta }>('/api/midpoint/meta'),
          api.get<{ config: Record<string, unknown> }>('/api/config'),
        ])
        if (!alive) return
        setMeta(m.meta)
        const sp = m.meta.specs[orient]
        const cfg = (c.config || {}) as Record<string, unknown>
        const pick = (k: string, l: string, d: string) => {
          const v = cfg[k] ?? cfg[l]
          return v === undefined || v === null ? d : String(v)
        }
        setStart(pick(sp.keys[0], sp.legacy[0], sp.defaults[0]))
        setLen(pick(sp.keys[1], sp.legacy[1], sp.defaults[1]))
        setWidth(pick(sp.keys[2], sp.legacy[2], sp.defaults[2]))
        setLayer(pick(sp.keys[3], sp.legacy[3], sp.defaults[3]))
        setForce(Boolean(cfg[sp.keys[4]]))
      } catch (e) {
        setStatusError(errText(e))
      }
    })()
    return () => {
      alive = false
    }
  }, [orient, setStatusError])

  // ---------------------------------------------------------- 存配置
  useEffect(() => {
    if (!keySig) return
    const keys = keySig.split(',')
    const t = window.setTimeout(() => {
      api
        .put('/api/config', {
          [keys[0]]: start,
          [keys[1]]: len,
          [keys[2]]: width,
          [keys[3]]: layer,
          [keys[4]]: force,
        })
        .catch(() => {})
    }, 500)
    return () => window.clearTimeout(t)
  }, [start, len, width, layer, force, keySig])

  // ---------------------------------------------------------- 读取
  const onRead = async () => {
    setBusy(true)
    setStatus('读取选中对象 …')
    try {
      const r = await api.post<{ lines: string[]; tracks: { row: string }[] }>(
        '/api/midpoint/read',
        { orient },
      )
      setLog((l) => [...l, ...r.lines])
      setTracks(r.tracks.map((t) => t.row))
      setStatus('读取选中对象 完成')
    } catch (e) {
      const msg = errText(e)
      setLog((l) => [...l, `❌ ${msg}`])
      setStatusError(msg)
      toast.danger(msg)
    } finally {
      setBusy(false)
    }
  }

  // ---------------------------------------------------------- 画线
  const onDraw = async () => {
    setBusy(true)
    setStatus('画中点短线 …')
    try {
      const r = await api.post<{ lines: string[]; skipped: boolean }>(
        '/api/midpoint/draw',
        {
          orient,
          start: Number(start),
          length: Number(len),
          width: Number(width),
          layer,
          force,
        },
      )
      setLog((l) => [...l, ...r.lines])
      if (r.skipped) {
        setStatus('目标位置已存在同规格线，已停止')
        toast.warning('目标位置已存在同规格线，已停止')
      } else {
        setStatus('画中点短线 完成')
        toast.success('已画线，并完成读回验证')
      }
    } catch (e) {
      const msg = errText(e)
      setLog((l) => [...l, `❌ ${msg}`])
      setStatusError(msg)
      toast.danger(msg)
    } finally {
      setBusy(false)
    }
  }

  const layerOptions = (meta?.layers ?? []).map((l) => ({
    value: l,
    label: l === '' ? '（跟随选中线所在层）' : l,
  }))
  const presetOptions = (meta?.presets ?? []).map((p) => ({
    value: String(p.value),
    label: p.label,
  }))

  return (
    <div className="pg-grid pg-grid--2" style={{ marginTop: 16 }}>
      <div className="pg-col">
        <Card>
          <CardHeader title="当前选中对象" description={spec?.require} />
          <CardBody>
            {tracks.length ? (
              <pre className="log ok-scroll" style={{ maxHeight: 220 }}>
                {tracks.join('\n')}
              </pre>
            ) : (
              <Text variant="caption" tone="subtle">
                （没有选中 track）
              </Text>
            )}
            <div style={{ marginTop: 12 }}>
              <Button variant="primary" onClick={onRead} loading={busy}>
                读取选中对象
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>

      <div className="pg-col">
        <Card>
          <CardHeader title="参数" description={spec?.hint} />
          <CardBody>
            <Grid minItemWidth={148} gap={4}>
              <Field label={spec?.startLabel ?? '起点'}>
                <Input value={start} onChange={setStart} inputMode="decimal" />
              </Field>
              <Field label="长度 (mil)">
                <Input value={len} onChange={setLen} inputMode="decimal" />
              </Field>
              <Field label="线宽 (mil)">
                <Input value={width} onChange={setWidth} inputMode="decimal" />
              </Field>
              <Field label="目标层" hint="留空 = 跟随选中线">
                <Select
                  value={layer}
                  options={layerOptions}
                  onChange={(v) => setLayer(v)}
                />
              </Field>
              <Field label="长度预设">
                <Select
                  value={''}
                  placeholder="选择预设…"
                  options={presetOptions}
                  onChange={(v) => {
                    setLen(v)
                    setStatus(`已填入长度预设 ${v} mil`)
                  }}
                />
              </Field>
              <Field label="允许重合（--force）">
                <Switch checked={force} onChange={setForce} />
              </Field>
            </Grid>
            <div style={{ marginTop: 14, display: 'flex', gap: 8 }}>
              <Button variant="accent" onClick={onDraw} loading={busy}>
                {spec?.button ?? '画中点短线'}
              </Button>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="日志" />
          <CardBody>
            <LogPanel lines={log} onClear={() => setLog([])} />
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
