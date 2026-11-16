import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CodeBlock,
  Field,
  Grid,
  Page,
  PageHeader,
  Select,
  Switch,
  Text,
  toast,
} from 'oink-ui'

import { api, errText } from '../api'
import LogPanel from '../components/LogPanel'
import type { GeneratedScript, PageProps } from '../types'

const COPY_MODES = [
  {
    value: 'api',
    label: 'api       - 快；多边形由 AD 自己重铺（形状按目标层规则）',
  },
  {
    value: 'clipboard',
    label: 'clipboard - 走 AD 原生复制粘贴；铺铜随复制一起搬（较慢）',
  },
]

export default function OverwritePage({
  setStatus,
  setStatusError,
  active,
}: PageProps) {
  const [names, setNames] = useState<string[]>([])
  const [source, setSource] = useState('尚未读取叠层 —— 请先点「读取当前 PCB 叠层」')
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [repour, setRepour] = useState(false)
  const [copyMode, setCopyMode] = useState('api')
  const [log, setLog] = useState<string[]>([])
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)

  const refreshLayers = useCallback(async () => {
    try {
      const c = await api.get<{
        confirmed: boolean
        names: string[]
      }>('/api/stackup/confirmed')
      if (c.confirmed && c.names?.length) {
        setNames((cur) => (cur.length ? cur : c.names))
      }
    } catch (e) {
      setStatusError(errText(e))
    }
  }, [setStatusError])

  useEffect(() => {
    if (active) refreshLayers()
  }, [active, refreshLayers])

  useEffect(() => {
    api
      .get<{ config: Record<string, unknown> }>('/api/config')
      .then((r) => {
        const cfg = r.config || {}
        if (cfg.ow_a) setA(String(cfg.ow_a))
        if (cfg.ow_b) setB(String(cfg.ow_b))
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!a && !b) return
    const t = window.setTimeout(() => {
      api.put('/api/config', { ow_a: a, ow_b: b }).catch(() => {})
    }, 400)
    return () => window.clearTimeout(t)
  }, [a, b])

  const onReadBoard = async () => {
    setBusy(true)
    setStatus('读取 PCB 叠层 …')
    try {
      const r = await api.get<{
        stackup: { board: string; copper: { name: string; copper_thickness_mils?: number }[] }
      }>('/api/pcb/stackup')
      const cop = r.stackup.copper ?? []
      if (!cop.length) {
        setLog((l) => [...l, '板子没返回叠层信息（可能没有打开 .PcbDoc）'])
        setStatusError('板子没返回叠层信息')
        return
      }
      const list = cop.map((x) => x.name)
      setNames(list)
      setSource(
        `来源：当前 PCB 实测 —— ${r.stackup.board || '(未知板)'}，共 ${list.length} 个铜层`,
      )
      setLog((l) => [
        ...l,
        `已读取当前 PCB 叠层：${r.stackup.board || '(未知板)'}`,
        ...cop.map(
          (x, i) =>
            `     ${String(i + 1).padStart(2)}. ${x.name.padEnd(10)} 铜厚 ${(
              x.copper_thickness_mils ?? 0
            ).toFixed(4)} mil`,
        ),
      ])
      setA((cur) => (list.includes(cur) ? cur : list[0]))
      setB((cur) =>
        list.includes(cur) && cur !== a ? cur : (list[1] ?? list[0]),
      )
      setStatus('叠层已读取')
    } catch (e) {
      const msg = errText(e)
      setLog((l) => [...l, `❌ 读取叠层失败：${msg}`])
      setStatusError(msg)
    } finally {
      setBusy(false)
    }
  }

  const onGenerate = async () => {
    setBusy(true)
    try {
      const r = await api.post<GeneratedScript>('/api/overwrite/generate', {
        a,
        b,
        repour,
        copyMode,
      })
      setLog((l) => [...l, ...r.log])
      setStatus('覆盖脚本已生成')
      toast.success('覆盖脚本已生成')
      try {
        const p = await api.get<{ body: string }>(
          `/api/overwrite/preview?path=${encodeURIComponent(r.pasPath)}`,
        )
        setPreview(p.body)
      } catch {
        /* 预览失败不影响主流程 */
      }
    } catch (e) {
      const msg = errText(e)
      setLog((l) => [...l, `❌ ${msg}`])
      setStatusError(msg)
    } finally {
      setBusy(false)
    }
  }

  const onOpenDir = async () => {
    try {
      await api.post('/api/script/open-dir')
      setStatus('已打开脚本目录')
    } catch (e) {
      setStatusError(errText(e))
    }
  }

  const options = names.map((n) => ({ value: n, label: n }))

  return (
    <Page size="full">
      <PageHeader
        title="叠层覆盖"
        description="A 层清空 → B 层内容复制到 A 层，B 层保留"
      />

      <div className="pg-grid pg-grid--2">
        <div className="pg-col">
          <Card>
            <CardHeader title="① 选层（建议先读板子）" />
            <CardBody>
              <Text variant="caption" tone="subtle" className="hint-text">
                {source}
              </Text>
              <div className="stack-gap" />
              <Grid minItemWidth={168} gap={4}>
                <Field label="层 A（被覆盖 / 会被清空）">
                  <Select
                    value={a}
                    options={options}
                    disabled={!names.length}
                    onChange={(v) => setA(v)}
                  />
                </Field>
                <Field label="层 B（来源 / 保留不动）">
                  <Select
                    value={b}
                    options={options}
                    disabled={!names.length}
                    onChange={(v) => setB(v)}
                  />
                </Field>
              </Grid>
              <div className="stack-gap" />
              <Grid minItemWidth={168} gap={4}>
                <Field
                  label="重新铺铜"
                  hint="按目标层规则重算；不勾选 = 保留搬过来的铺铜形状"
                >
                  <Switch checked={repour} onChange={setRepour} />
                </Field>
                <Field label="复制方式">
                  <Select
                    value={copyMode}
                    options={COPY_MODES}
                    onChange={(v) => setCopyMode(v)}
                  />
                </Field>
              </Grid>
              <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                <Button
                  variant="accent"
                  onClick={onGenerate}
                  loading={busy}
                  disabled={!a || !b || a === b}
                >
                  生成覆盖脚本
                </Button>
                <Button variant="soft" onClick={onReadBoard} loading={busy}>
                  读取当前 PCB 叠层
                </Button>
                <Button variant="ghost" onClick={onOpenDir}>
                  打开脚本目录
                </Button>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="执行方式" />
            <CardBody>
              <Text variant="caption" tone="subtle" className="hint-text">
                生成的是一份 DelphiScript（文件名带时间戳）：到 AD 里 File → Run Script…
                选刚生成的那个 .PrjScr，过程名 OverwriteLayer。
                <br />
                跑完先看计数（A 应等于原 B 的数量、B 不变），确认无误再按 Ctrl+S 保存。
              </Text>
            </CardBody>
          </Card>
        </div>

        <div className="pg-col">
          <Card>
            <CardHeader title="输出" />
            <CardBody>
              <LogPanel lines={log} onClear={() => setLog([])} />
              {preview && (
                <>
                  <div className="stack-gap" />
                  <CodeBlock
                    code={preview}
                    language="pascal"
                    title="overwrite_layer.pas"
                    wrap
                    maxHeight={320}
                  />
                </>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </Page>
  )
}
