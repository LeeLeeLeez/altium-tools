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
  Text,
  toast,
} from 'oink-ui'

import { api, errText } from '../api'
import LogPanel from '../components/LogPanel'
import type { GeneratedScript, PageProps } from '../types'

export default function SwapPage({ setStatus, setStatusError, active }: PageProps) {
  const [names, setNames] = useState<string[]>([])
  const [source, setSource] = useState('尚未确认叠层')
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [map, setMap] = useState('')
  const [valid, setValid] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)

  // -------------------------------------------------- 层名来源
  const refreshLayers = useCallback(async () => {
    try {
      const c = await api.get<{ confirmed: boolean; names: string[]; label: string }>(
        '/api/stackup/confirmed',
      )
      if (!c.confirmed || !c.names?.length) {
        setNames([])
        setSource(
          '⚠️ 尚未确认叠层 —— 请先到「叠层设计」页，点「确认叠层」，本页才能读到层名。',
        )
        setValid(false)
        return
      }
      setNames(c.names)
      setSource(`来源：叠层设计已确认，共 ${c.names.length} 个铜层（${c.names[0]} … ${c.names[c.names.length - 1]}）`)
      setA((cur) => {
        if (cur && c.names.includes(cur)) return cur
        return c.names[0]
      })
      setB((cur) => {
        if (cur && c.names.includes(cur) && cur !== a) return cur
        const cand = c.names.find((n) => n.startsWith('L1'))
        if (cand && cand !== c.names[0]) return cand
        return c.names[1] ?? c.names[0]
      })
    } catch (e) {
      setStatusError(errText(e))
    }
  }, [a, setStatusError])

  useEffect(() => {
    if (active) refreshLayers()
  }, [active, refreshLayers])

  // 读配置里的 A/B
  useEffect(() => {
    api
      .get<{ config: Record<string, unknown> }>('/api/config')
      .then((r) => {
        const cfg = r.config || {}
        if (cfg.swap_a) setA(String(cfg.swap_a))
        if (cfg.swap_b) setB(String(cfg.swap_b))
      })
      .catch(() => {})
  }, [])

  // 存 A/B
  useEffect(() => {
    if (!a && !b) return
    const t = window.setTimeout(() => {
      api.put('/api/config', { swap_a: a, swap_b: b }).catch(() => {})
    }, 400)
    return () => window.clearTimeout(t)
  }, [a, b])

  // -------------------------------------------------- 校验
  useEffect(() => {
    if (!a || !b || !names.length) {
      setMap('')
      setValid(false)
      return
    }
    let alive = true
    api
      .post<{ ok: boolean; error?: string; map?: string }>('/api/swap/validate', {
        a,
        b,
      })
      .then((r) => {
        if (!alive) return
        if (r.ok) {
          setMap(r.map ?? '')
          setValid(true)
        } else {
          setMap(`⚠️ ${r.error}`)
          setValid(false)
        }
      })
      .catch((e) => {
        if (alive) setStatusError(errText(e))
      })
    return () => {
      alive = false
    }
  }, [a, b, names.length, setStatusError])

  // -------------------------------------------------- 操作
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
        `✅ 已读取当前 PCB 叠层：${r.stackup.board || '(未知板)'}`,
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
      const r = await api.post<GeneratedScript>('/api/swap/generate', { a, b })
      setLog((l) => [...l, ...r.log])
      setStatus('交换脚本已生成')
      toast.success('交换脚本已生成')
      try {
        const p = await api.get<{ body: string }>(
          `/api/swap/preview?path=${encodeURIComponent(r.pasPath)}`,
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
        title="层交换"
        description="把两层铜箔上的全部图元互换（排除 via / board cutout / 元件）"
      />

      <div className="pg-grid pg-grid--2">
        <div className="pg-col">
          <Card>
            <CardHeader title="层选择" />
            <CardBody>
              <Text variant="caption" tone="subtle" className="hint-text">
                {source}
              </Text>
              <div className="stack-gap" />
              <Grid minItemWidth={168} gap={4}>
                <Field label="层 A（原始）">
                  <Select
                    value={a}
                    options={options}
                    disabled={!names.length}
                    onChange={(v) => setA(v)}
                  />
                </Field>
                <Field label="层 B（目标）">
                  <Select
                    value={b}
                    options={options}
                    disabled={!names.length}
                    onChange={(v) => setB(v)}
                  />
                </Field>
              </Grid>
              <div className="stack-gap" />
              <Text variant="body" className="mono">
                {map}
              </Text>
              <Text variant="caption" tone="subtle">
                中转层由脚本自动挑选（第一个空闲的 MidLayer）
              </Text>
              <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                <Button
                  variant="accent"
                  onClick={onGenerate}
                  loading={busy}
                  disabled={!valid}
                >
                  生成交换脚本
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
            <CardHeader title="执行方式（必须人工）" />
            <CardBody>
              <Text variant="caption" tone="subtle" className="hint-text">
                1. 在 AD 里先只打开目标 .PcbDoc
                <br />
                2. File → Run Script… → 选刚生成的那个 .PrjScr
                <br />
                3. 过程名选 SwapLayers
                <br />
                4. 核对弹窗上的层名与数量，再按 OK
                <br />
                5. Ctrl+S 保存；不满意就 Ctrl+Z
                <br />
                <br />
                脚本会先把 A 层图元搬到中转层，再把 B 层搬到 A，最后把中转层搬到 B ——
                中转是为了避免两层互相打架。
              </Text>
            </CardBody>
          </Card>
        </div>

        <div className="pg-col">
          <Card>
            <CardHeader title="生成结果 / 预览" />
            <CardBody>
              <LogPanel lines={log} onClear={() => setLog([])} />
              {preview && (
                <>
                  <div className="stack-gap" />
                  <CodeBlock
                    code={preview}
                    language="pascal"
                    title="swap_layers.pas"
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
