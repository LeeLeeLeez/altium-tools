import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardHeader,
  Dialog,
  Field,
  Grid,
  Input,
  Page,
  PageHeader,
  Select,
  Stat,
  Text,
  confirm,
  toast,
} from 'oink-ui'

import { api, errText } from '../api'
import LogPanel from '../components/LogPanel'
import type { PageProps, SnapshotPlan, SnapshotScan } from '../types'

interface BrowseResult {
  path: string
  parent: string | null
  exists: boolean
  dirs: { name: string; path: string }[]
  error?: string
}

export default function SnapshotPage({ setStatus, setStatusError }: PageProps) {
  const [root, setRoot] = useState('')
  const [roots, setRoots] = useState<string[]>([])
  const [lastDst, setLastDst] = useState('')
  const [scan, setScan] = useState<SnapshotScan | null>(null)
  const [plan, setPlan] = useState<SnapshotPlan | null>(null)
  const [log, setLog] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [browseOpen, setBrowseOpen] = useState(false)
  const [browse, setBrowse] = useState<BrowseResult | null>(null)
  const [browsePath, setBrowsePath] = useState('')

  const loadConfig = useCallback(async () => {
    try {
      const r = await api.get<{
        config: {
          snapRoot: string
          snapRoots: string[]
          snapLastDst: string
          defaultRoot: string
        }
      }>('/api/snapshot/config')
      setRoot(r.config.snapRoot || '')
      setRoots(r.config.snapRoots || [])
      setLastDst(r.config.snapLastDst || '')
      if (!r.config.snapRoot) setBrowsePath(r.config.defaultRoot || '')
    } catch (e) {
      setStatusError(errText(e))
    }
  }, [setStatusError])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  const saveConfig = (nextRoot: string, dst?: string) => {
    api
      .put('/api/snapshot/config', {
        snapRoot: nextRoot,
        snapRoots: [nextRoot, ...roots.filter((r) => r !== nextRoot)].slice(0, 6),
        snapLastDst: dst ?? lastDst,
      })
      .catch(() => {})
  }

  const onScan = async () => {
    setBusy(true)
    setStatus('扫描快照库 …')
    try {
      const r = await api.get<SnapshotScan>(
        `/api/snapshot/scan?root=${encodeURIComponent(root)}`,
      )
      setScan(r)
      saveConfig(root)
      setLog((l) => [
        ...l,
        `共 ${r.counts.dates} 个日期目录 / ${r.counts.snaps} 个快照　|　源：${r.source?.rel ?? '—'}`,
      ])
      if (r.note) setLog((l) => [...l, `⚠️ ${r.note}`])
      setStatus('扫描完成')
    } catch (e) {
      const msg = errText(e)
      setLog((l) => [...l, `❌ ${msg}`])
      setStatusError(msg)
    } finally {
      setBusy(false)
    }
  }

  const onPreview = async () => {
    setBusy(true)
    try {
      const r = await api.get<{ plan: SnapshotPlan }>(
        `/api/snapshot/plan?root=${encodeURIComponent(root)}`,
      )
      setPlan(r.plan)
      setLog((l) => [
        ...l,
        `预览（未写盘）：${r.plan.dst}`,
        `待拷 ${r.plan.files.length} 个文件，共 ${r.plan.human}`,
      ])
      if (r.plan.pcbNote) setLog((l) => [...l, `ℹ️ ${r.plan.pcbNote}`])
      setStatus('预览完成')
    } catch (e) {
      const msg = errText(e)
      setLog((l) => [...l, `❌ ${msg}`])
      setStatusError(msg)
    } finally {
      setBusy(false)
    }
  }

  const onCreate = async () => {
    const ok = await confirm({
      title: '新建快照',
      description: `源：${scan?.source?.rel ?? '—'}\n目标：${plan?.dst ?? '（自动生成）'}\n待拷：${
        plan?.files.length ?? '?'
      } 个文件\n继续？`,
      confirmText: '继续',
    })
    if (!ok) return
    setBusy(true)
    setStatus('正在新建快照 …')
    try {
      const r = await api.post<{
        ok: boolean
        dst: string
        count: number
        errors: string[]
        missing: string[]
        size_bad: string[]
        sha_bad: string[]
        log: string[]
      }>('/api/snapshot/create', { root })
      setLog((l) => [...l, ...(r.log ?? [])])
      if (r.ok) {
        setLastDst(r.dst)
        saveConfig(root, r.dst)
        setStatus(`快照已建好：${r.dst}`)
        toast.success('快照已建好')
        await onScan()
      } else {
        setLog((l) => [
          ...l,
          `❌ 新建失败：${r.errors.join('；') || '文件校验未通过'}`,
          ...r.missing.map((x) => `   缺失 ${x}`),
          ...r.size_bad.map((x) => `   大小不符 ${x}`),
          ...r.sha_bad.map((x) => `   校验不符 ${x}`),
        ])
        setStatusError('新建快照有异常')
      }
    } catch (e) {
      const msg = errText(e)
      setLog((l) => [...l, `❌ ${msg}`])
      setStatusError(msg)
    } finally {
      setBusy(false)
    }
  }

  const onReveal = async (path: string) => {
    try {
      await api.post('/api/snapshot/reveal', { path })
      setStatus('已打开目录')
    } catch (e) {
      setStatusError(errText(e))
    }
  }

  const onBrowse = async (path: string) => {
    try {
      const r = await api.get<BrowseResult>(
        `/api/snapshot/browse?path=${encodeURIComponent(path)}`,
      )
      setBrowse(r)
      setBrowsePath(r.path)
    } catch (e) {
      setStatusError(errText(e))
    }
  }

  const openBrowse = async () => {
    setBrowseOpen(true)
    await onBrowse(browsePath || root || 'E:\\')
  }

  return (
    <Page size="full">
      <PageHeader
        title="工程快照"
        description="日期文件夹 → 时间戳文件夹 → 拷工程本体 → PrjPcb 加时间戳后缀"
      />

      <div className="pg-grid pg-grid--2">
        <div className="pg-col">
          <Card>
            <CardHeader title="① 快照库位置" />
            <CardBody>
              <Field label="根目录">
                <Input
                  value={root}
                  placeholder="E:\\project\\800-6\\PCB_prj\\A4_prj"
                  onChange={(v) => setRoot(v)}
                />
              </Field>
              <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                <Button variant="soft" onClick={openBrowse}>
                  浏览…
                </Button>
                <Button variant="primary" onClick={onScan} loading={busy}>
                  扫描
                </Button>
                {roots.length > 0 && (
                  <Select
                    size="sm"
                    value=""
                    placeholder="最近目录…"
                    options={roots.map((r) => ({ value: r, label: r }))}
                    onChange={(v) => {
                      setRoot(v)
                      saveConfig(v)
                    }}
                  />
                )}
              </div>
              {scan && (
                <>
                  <div className="stack-gap" />
                  <Text variant="body">
                    共 {scan.counts.dates} 个日期目录 / {scan.counts.snaps} 个快照　|　源：
                    {scan.source?.rel ?? '—'}
                  </Text>
                </>
              )}
              {scan?.note && (
                <div style={{ marginTop: 10 }}>
                  <Alert tone="warning" title="目录名与写入时间不一致">
                    {scan.note}
                  </Alert>
                </div>
              )}
              <div className="stack-gap" />
              <Text variant="caption" tone="subtle" className="hint-text">
                约定：根目录下按 <span className="mono">&lt;YYYYMMDD&gt;/&lt;YYYYMMDDHHMM&gt;/</span>{' '}
                存放各轮快照；只拷工程本体（.SchDoc/.PcbDoc/.BomDoc/.PrjPcb/.PrjPcbStructure 等），
                History、__Previews、_copy_/_plain_/.bak_/zip 一律跳过。
              </Text>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="② 新建" />
            <CardBody>
              {plan ? (
                <>
                  <Grid minItemWidth={150} gap={3}>
                    <Stat label="待拷文件" value={`${plan.files.length}`} variant="card" />
                    <Stat label="体积" value={plan.human} variant="card" />
                  </Grid>
                  <div className="stack-gap" />
                  <Text variant="caption" className="mono">
                    {plan.dst}
                  </Text>
                  {plan.pcbNote && (
                    <>
                      <div className="stack-gap" />
                      <Text variant="caption" tone="subtle">
                        ℹ️ {plan.pcbNote}
                      </Text>
                    </>
                  )}
                </>
              ) : (
                <Text variant="caption" tone="subtle">
                  点「扫描」后这里会显示将要生成的目标与待拷文件数。
                </Text>
              )}
              <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                <Button variant="soft" onClick={onPreview} loading={busy}>
                  预览（不落盘）
                </Button>
                <Button variant="accent" onClick={onCreate} loading={busy}>
                  新建快照
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => onReveal(lastDst || scan?.source?.path || root)}
                  disabled={!lastDst && !scan?.source?.path}
                >
                  打开快照目录
                </Button>
              </div>
            </CardBody>
          </Card>
        </div>

        <div className="pg-col">
          <Card>
            <CardHeader title="输出" />
            <CardBody>
              <LogPanel lines={log} onClear={() => setLog([])} />
            </CardBody>
          </Card>
        </div>
      </div>

      <Dialog
        open={browseOpen}
        onOpenChange={setBrowseOpen}
        title="选择快照库根目录"
        description="在服务器上浏览目录（浏览器选不到本机路径）"
        size="lg"
      >
        <div className="pg-col" style={{ gap: 8 }}>
          <Field label="路径">
            <Input value={browsePath} onChange={(v) => setBrowsePath(v)} />
          </Field>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" onClick={() => onBrowse(browsePath)}>
              打开
            </Button>
            {browse?.parent && (
              <Button variant="ghost" onClick={() => onBrowse(browse.parent!)}>
                上级目录
              </Button>
            )}
          </div>
          <div style={{ maxHeight: 300, overflow: 'auto' }}>
            {(browse?.dirs ?? []).map((d) => (
              <Button
                key={d.path}
                variant="ghost"
                block
                onClick={() => onBrowse(d.path)}
              >
                {d.name}
              </Button>
            ))}
            {browse && !browse.exists && (
              <Text variant="caption" tone="danger">
                目录不存在
              </Text>
            )}
          </div>
          <Button
            variant="accent"
            block
            onClick={() => {
              setRoot(browsePath)
              saveConfig(browsePath)
              setBrowseOpen(false)
            }}
          >
            用这个目录
          </Button>
        </div>
      </Dialog>
    </Page>
  )
}
