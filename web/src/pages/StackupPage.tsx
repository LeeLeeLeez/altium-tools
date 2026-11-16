import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  DescriptionList,
  Dialog,
  Field,
  Grid,
  Input,
  Page,
  PageHeader,
  Segmented,
  Select,
  Stat,
  Table,
  Text,
  toast,
} from 'oink-ui'
import type { TableColumn } from 'oink-ui'

import { api, errText } from '../api'
import LayerStrip from '../components/LayerStrip'
import LogPanel from '../components/LogPanel'
import MmfChart from '../components/MmfChart'
import type { PageProps, StackupRow, StackupState } from '../types'

const fmt = (um: number | undefined) =>
  um === undefined ? '—' : `${(um / 1000).toFixed(4)} mm`

export default function StackupPage({ setStatus, setStatusError }: PageProps) {
  const [state, setState] = useState<StackupState | null>(null)
  const [params, setParams] = useState<Record<string, string>>({})
  const [rect, setRect] = useState('fullwave')
  const [cumode, setCumode] = useState('global')
  const [log, setLog] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [tplOpen, setTplOpen] = useState(false)
  const [tplFiles, setTplFiles] = useState<
    { name: string; path: string; size: number; mtime: string }[]
  >([])
  const lastPush = useRef('')

  const sigOf = (p: Record<string, string>, r: string, c: string) =>
    JSON.stringify([p, r, c])

  const apply = useCallback((s: StackupState) => {
    setState(s)
    setParams(s.params)
    setRect(s.rect)
    setCumode(s.cumode)
    lastPush.current = JSON.stringify([s.params, s.rect, s.cumode])
  }, [])

  const load = useCallback(async () => {
    try {
      apply(await api.get<StackupState>('/api/stackup/state'))
    } catch (e) {
      setStatusError(errText(e))
    }
  }, [apply, setStatusError])

  useEffect(() => {
    load()
  }, [load])

  // 参数改动 → 防抖 → 推给后端重建
  useEffect(() => {
    if (!state) return
    const sig = sigOf(params, rect, cumode)
    if (sig === lastPush.current) return
    const t = window.setTimeout(async () => {
      lastPush.current = sig
      try {
        const s = await api.post<StackupState>('/api/stackup/params', {
          ...params,
          rect,
          cumode,
        })
        setState(s)
      } catch (e) {
        setStatusError(errText(e))
      }
    }, 600)
    return () => window.clearTimeout(t)
  }, [params, rect, cumode, state, setStatusError])

  const setParam = (k: string, v: string) =>
    setParams((p) => ({ ...p, [k]: v }))

  // ---------------------------------------------------------- 行编辑
  const onRowType = async (index: number, type: string) => {
    setBusy(true)
    try {
      const s = await api.post<StackupState>('/api/stackup/row-type', {
        index,
        type,
      })
      setState(s)
      setStatus('层类型已改动，需重新确认叠层')
    } catch (e) {
      setStatusError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  const onRowOz = async (index: number, oz: string) => {
    setBusy(true)
    try {
      const s = await api.post<StackupState>('/api/stackup/row-oz', {
        index,
        oz,
      })
      setState(s)
    } catch (e) {
      setStatusError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  // ---------------------------------------------------------- 操作
  const onRebuild = async () => {
    setBusy(true)
    try {
      const s = await api.post<StackupState>('/api/stackup/params', {
        ...params,
        rect,
        cumode,
      })
      setState(s)
      lastPush.current = sigOf(params, rect, cumode)
      setLog((l) => [...l, '已重建叠层序列'])
      setStatus('叠层序列已重建')
    } catch (e) {
      setStatusError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  const onSyncCu = async () => {
    setBusy(true)
    try {
      const s = await api.post<StackupState>('/api/stackup/sync-cu')
      setState(s)
      setLog((l) => [...l, '已按原副边同步铜厚'])
      setStatus('已按原副边同步铜厚')
    } catch (e) {
      setStatusError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  const onConfirm = async () => {
    setBusy(true)
    try {
      const r = await api.post<{ message?: string; error?: string }>(
        '/api/stackup/confirm',
      )
      if (r.error) {
        setLog((l) => [...l, `⚠️ ${r.error}`])
        setStatusError(r.error)
      } else {
        setLog((l) => [...l, r.message ?? '已确认叠层'])
        setStatus('叠层已确认')
        toast.success('叠层已确认，层交换页现在可以读到层名了')
      }
      await load()
    } catch (e) {
      setStatusError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  const onOpenTemplates = async () => {
    setTplOpen(true)
    try {
      const r = await api.get<{ files: typeof tplFiles; error?: string }>(
        '/api/stackup/templates',
      )
      setTplFiles(r.files ?? [])
      if (r.error) setLog((l) => [...l, `⚠️ ${r.error}`])
    } catch (e) {
      setStatusError(errText(e))
    }
  }

  const onPickTemplate = async (path: string) => {
    setBusy(true)
    try {
      const r = await api.post<{
        state: StackupState
        label: string
        note?: string
      }>('/api/stackup/template/open', { path })
      setState(r.state)
      setTplOpen(false)
      setLog((l) => [...l, `✅ 读入 ${r.label}`])
      if (r.note) setLog((l) => [...l, r.note as string])
      setStatus('已读入叠层模板')
    } catch (e) {
      setStatusError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  const onWrite = async () => {
    setBusy(true)
    setStatus('写出 .stackup …')
    try {
      const r = await api.post<{ message?: string; error?: string }>(
        '/api/stackup/write',
      )
      if (r.error) {
        setLog((l) => [...l, `❌ ${r.error}`])
        setStatusError(r.error)
      } else {
        setLog((l) => [...l, r.message ?? '已写出'])
        setStatus('已写出 .stackup')
        toast.success('已写出 .stackup')
      }
    } catch (e) {
      const msg = errText(e)
      setLog((l) => [...l, `❌ ${msg}`])
      setStatusError(msg)
    } finally {
      setBusy(false)
    }
  }

  // ---------------------------------------------------------- 表格
  const typeOptions = (state?.typeLabels ?? []).map((t) => ({
    value: t.value,
    label: t.label,
  }))
  const cuOptions = (state?.cuChoices ?? []).map((c) => ({ value: c, label: c }))
  const perLayerEditable = state?.cuMode.perLayerEditable ?? false

  const columns: TableColumn<StackupRow>[] = [
    { key: 'i', header: '#', width: 42 },
    {
      key: 'name',
      header: '层名',
      width: '26%',
      render: (r) => <span className="layer-table__name">{r.name}</span>,
    },
    {
      key: 'type',
      header: '类型',
      width: 132,
      render: (r) => (
        <Select
          size="sm"
          value={r.type}
          options={typeOptions}
          onChange={(v) => onRowType(r.i - 1, v)}
        />
      ),
    },
    {
      key: 'oz',
      header: '铜厚',
      width: 104,
      hideBelow: 'md',
      render: (r) => (
        <Select
          size="sm"
          value={r.ozText}
          options={cuOptions}
          disabled={!perLayerEditable}
          onChange={(v) => onRowOz(r.i - 1, v)}
        />
      ),
    },
    {
      key: 'gap',
      header: '介质 µm',
      width: 96,
      align: 'end',
      hideBelow: 'sm',
      render: (r) => (r.gap === null ? '—' : String(r.gap)),
    },
  ]

  const result = state?.result ?? null

  return (
    <Page size="full">
      <PageHeader
        title="叠层设计"
        description="层序列 P/S/A/B/G → 板厚 · 仿真厚度 · MMF　层名规则：top - L1_x - … - Bot"
      />

      {state?.error && (
        <div style={{ marginBottom: 12 }}>
          <Text variant="body" tone="danger">
            ⚠️ {state.error}
          </Text>
        </div>
      )}

      <div className="pg-grid pg-grid--3">
        {/* ------------------------------------------------ 左：参数 */}
        <div className="pg-col">
          <Card>
            <CardHeader title="叠层参数" />
            <CardBody>
              <Grid minItemWidth={132} gap={4}>
                <Field label="原边层数 Lp">
                  <Input
                    value={params.Lp ?? ''}
                    onChange={(v) => setParam('Lp', v)}
                  />
                </Field>
                <Field label="副边层数 Ls">
                  <Input
                    value={params.Ls ?? ''}
                    onChange={(v) => setParam('Ls', v)}
                  />
                </Field>
                <Field label="GND 层数 Lgnd">
                  <Input
                    value={params.Lgnd ?? ''}
                    onChange={(v) => setParam('Lgnd', v)}
                  />
                </Field>
                <Field label="GND 位置" hint="逗号分隔；留空=自动取顶/底">
                  <Input
                    value={params.gnd ?? ''}
                    onChange={(v) => setParam('gnd', v)}
                  />
                </Field>
                <Field label="原边匝数 Np" hint="须整除 Lp">
                  <Input
                    value={params.Np ?? ''}
                    onChange={(v) => setParam('Np', v)}
                  />
                </Field>
                <Field label="副边匝数 Ns" hint="须整除 Larm">
                  <Input
                    value={params.Ns ?? ''}
                    onChange={(v) => setParam('Ns', v)}
                  />
                </Field>
              </Grid>

              <div className="stack-gap" />
              <Field label="整流方式">
                <Segmented
                  value={rect}
                  options={[
                    { value: 'fullwave', label: '全波' },
                    { value: 'fullbridge', label: '全桥' },
                  ]}
                  onChange={(v) => setRect(v)}
                />
              </Field>

              <div className="stack-gap" />
              <Field label="铜厚模式">
                <Segmented
                  value={cumode}
                  options={[
                    { value: 'global', label: '按原副边' },
                    { value: 'perlayer', label: '逐层单独指定' },
                  ]}
                  onChange={(v) => setCumode(v)}
                />
              </Field>

              <div className="stack-gap" />
              <Grid minItemWidth={104} gap={3}>
                <Field label="原边铜厚">
                  <Select
                    size="sm"
                    value={params.ozP ?? ''}
                    options={cuOptions}
                    disabled={!state?.cuMode.globalEditable}
                    onChange={(v) => setParam('ozP', v)}
                  />
                </Field>
                <Field label="副边铜厚">
                  <Select
                    size="sm"
                    value={params.ozS ?? ''}
                    options={cuOptions}
                    disabled={!state?.cuMode.globalEditable}
                    onChange={(v) => setParam('ozS', v)}
                  />
                </Field>
                <Field label="GND 铜厚">
                  <Select
                    size="sm"
                    value={params.ozG ?? ''}
                    options={cuOptions}
                    disabled={!state?.cuMode.globalEditable}
                    onChange={(v) => setParam('ozG', v)}
                  />
                </Field>
              </Grid>

              <div className="stack-gap" />
              <Text variant="label">层间距 (µm)</Text>
              <div className="stack-gap" />
              <Grid minItemWidth={96} gap={3}>
                <Field label="P–P">
                  <Input
                    size="sm"
                    value={params.dPP ?? ''}
                    onChange={(v) => setParam('dPP', v)}
                  />
                </Field>
                <Field label="副边/GND–副边">
                  <Input
                    size="sm"
                    value={params.dSS ?? ''}
                    onChange={(v) => setParam('dSS', v)}
                  />
                </Field>
                <Field label="P–副边">
                  <Input
                    size="sm"
                    value={params.dPS ?? ''}
                    onChange={(v) => setParam('dPS', v)}
                  />
                </Field>
              </Grid>

              <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                <Button variant="accent" onClick={onRebuild} loading={busy}>
                  重建叠层序列
                </Button>
                <Button variant="soft" onClick={onSyncCu} loading={busy}>
                  按原副边同步铜厚
                </Button>
              </div>
            </CardBody>
          </Card>
        </div>

        {/* ------------------------------------------------ 中：序列 + MMF */}
        <div className="pg-col">
          <Card>
            <CardHeader
              title="叠层序列（自上而下：top → Bot）"
              description={state?.confirmed.label}
              actions={
                <Button
                  variant="primary"
                  size="sm"
                  onClick={onConfirm}
                  loading={busy}
                >
                  确认叠层
                </Button>
              }
            />
            <CardBody>
              {/* 层序色带横排在表格上方：不占用表格横向空间 */}
              <LayerStrip strip={state?.strip ?? []} />
              <div style={{ height: 10 }} />
              <Table
                className="layer-table"
                label="叠层序列"
                columns={columns}
                data={state?.rows ?? []}
                rowKey="i"
                scroll
                maxHeight="min(56vh, 760px)"
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="MMF 磁动势分布"
              description="纵轴=层序 顶→底，横轴=安匝"
            />
            <CardBody>
              <MmfChart series={state?.mmfSeries ?? []} />
            </CardBody>
          </Card>
        </div>

        {/* ------------------------------------------------ 右：结果 + 文件 */}
        <div className="pg-col pg-col--right">
          <Card>
            <CardHeader title="计算结果" />
            <CardBody>
              {result ? (
                <>
                  <Grid minItemWidth={150} gap={3}>
                    <Stat
                      label="总板厚"
                      value={fmt(result.total)}
                      variant="card"
                    />
                    <Stat
                      label="仿真厚度"
                      value={fmt(result.simTotal)}
                      variant="card"
                    />
                  </Grid>
                  <div className="stack-gap" />
                  <DescriptionList
                    divided
                    items={[
                      { term: '层数', description: `${state?.seq.length ?? 0}` },
                      {
                        term: '类型分布',
                        description: `P ${result.counts.P} / S ${result.counts.S} / A ${result.counts.A} / B ${result.counts.B} / G ${result.counts.G}`,
                      },
                      { term: '铜厚模式', description: result.mode },
                      { term: '铜合计', description: fmt(result.cu) },
                      { term: '介质合计', description: fmt(result.diel) },
                      {
                        term: '安匝 ATp / ATs',
                        description: `${result.ATp.toFixed(3)} / ${result.ATs.toFixed(3)} A`,
                      },
                      { term: '原副边界面数', description: `${result.iface}` },
                      {
                        term: 'MMF peak',
                        description: `${result.mmf.peak.toFixed(1)} A`,
                      },
                      {
                        term: 'MMF integral',
                        description: `${result.mmf.integral.toFixed(1)} A`,
                      },
                      {
                        term: 'MMF 对称偏差',
                        description: `${result.mmf.sym.toFixed(1)} A`,
                      },
                    ]}
                  />
                  {result.errors.length > 0 && (
                    <>
                      <div className="stack-gap" />
                      {result.errors.map((e) => (
                        <Text key={e} variant="caption" tone="danger">
                          ⚠️ {e}
                        </Text>
                      ))}
                    </>
                  )}
                </>
              ) : (
                <Text variant="caption" tone="subtle">
                  —
                </Text>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="与 AD 板子对接" />
            <CardBody>
              <Text variant="body" className="hint-text">
                {state?.template.label ?? '未读入模板 —— 写出时将「从零生成」'}
              </Text>
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <Button variant="soft" onClick={onOpenTemplates}>
                  读入 .stackup
                </Button>
                <Button variant="accent" onClick={onWrite} loading={busy}>
                  写出 .stackup
                </Button>
              </div>
              <div className="stack-gap" />
              <Text variant="caption" tone="subtle" className="hint-text">
                模板可选：读入 LSM 导出的 .stackup ⇒ 保留板子的材料/过孔跨度等设置；
                流程：调设计 → 写出 → LSM 里 File → Load Stackup From File 导入。
              </Text>
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

      <Dialog
        open={tplOpen}
        onOpenChange={setTplOpen}
        title="选择叠层模板"
        description="AD 导出的 .stackup 文件"
        size="lg"
      >
        <div className="pg-col" style={{ gap: 8 }}>
          {tplFiles.length === 0 && (
            <Text variant="caption" tone="subtle">
              目录里没有 .stackup 文件。
            </Text>
          )}
          {tplFiles.map((f) => (
            <Button
              key={f.path}
              variant="soft"
              block
              onClick={() => onPickTemplate(f.path)}
            >
              {f.name} · {Math.round(f.size / 1024)} KB · {f.mtime}
            </Button>
          ))}
        </div>
      </Dialog>
    </Page>
  )
}
