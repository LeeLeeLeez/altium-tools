import { useCallback, useEffect, useState } from 'react'
import {
  AppShell,
  Badge,
  Button,
  Confirmer,
  Icon,
  Nav,
  NavGroup,
  NavItem,
  OinkProvider,
  Toaster,
  useOink,
} from 'oink-ui'

import OverviewPage from './pages/OverviewPage'
import MidpointPage from './pages/MidpointPage'
import StackupPage from './pages/StackupPage'
import SwapPage from './pages/SwapPage'
import OverwritePage from './pages/OverwritePage'
import SnapshotPage from './pages/SnapshotPage'

type IconName = React.ComponentProps<typeof Icon>['name']

interface NavDef {
  group: string
  items: { id: string; text: string; icon: IconName }[]
}

const NAV: NavDef[] = [
  {
    group: '原理图操作',
    items: [{ id: 'overview', text: '概览', icon: 'file' }],
  },
  {
    group: 'PCB 操作',
    items: [
      { id: 'midpoint', text: '画中点短线', icon: 'grid' },
      { id: 'stackup', text: '叠层设计', icon: 'layout' },
      { id: 'swap', text: '层交换', icon: 'shuffle' },
      { id: 'overwrite', text: '叠层覆盖', icon: 'copy' },
    ],
  },
  {
    group: '工程管理',
    items: [{ id: 'snapshot', text: '工程快照', icon: 'archive' }],
  },
]

export default function App() {
  return (
    <OinkProvider
      defaultTheme="system"
      defaultAccent="blue"
      locale="zh-CN"
      storageKey="altium-tools"
    >
      <Shell />
      <Toaster />
      <Confirmer />
    </OinkProvider>
  )
}

function Shell() {
  // 支持 ?page=stackup 这样的深链（截图/自动化/外部跳转都用得上）
  const [page, setPage] = useState(() => {
    try {
      const p = new URLSearchParams(window.location.search).get('page')
      const ok = NAV.some((g) => g.items.some((i) => i.id === p))
      return ok ? (p as string) : 'midpoint'
    } catch {
      return 'midpoint'
    }
  })
  const [status, setStatus] = useState('就绪')
  const [statusError, setStatusError] = useState(false)
  const [bridge, setBridge] = useState<{ connected: boolean }>({ connected: false })
  const { resolvedTheme, setTheme } = useOink()

  const setStatusSafe = useCallback((msg: string) => {
    setStatus(msg)
    setStatusError(false)
  }, [])

  const setStatusErrorSafe = useCallback((msg: string) => {
    setStatus(msg)
    setStatusError(true)
  }, [])

  useEffect(() => {
    let alive = true
    const tick = () =>
      fetch('/api/bridge/status')
        .then((r) => r.json())
        .then((d) => {
          if (alive && d?.status) setBridge(d.status)
        })
        .catch(() => {})
    tick()
    const t = window.setInterval(tick, 10000)
    return () => {
      alive = false
      window.clearInterval(t)
    }
  }, [])

  const shared = {
    setStatus: setStatusSafe,
    setStatusError: setStatusErrorSafe,
    active: page,
  }

  return (
    <AppShell collapseBelow="md">
      <AppShell.Header>
        <div className="appbar">
          <AppShell.Trigger target="sidebar" />
          <span className="appbar__title">Altium 工具集</span>
          <Badge tone={bridge.connected ? 'success' : 'neutral'} variant="soft">
            {bridge.connected ? 'AD 桥接已连接' : 'AD 桥接未连接'}
          </Badge>
          <span className="appbar__spacer" />
          <Button
            size="sm"
            variant="ghost"
            leading={<Icon name={resolvedTheme === 'dark' ? 'sun' : 'moon'} />}
            onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
          >
            {resolvedTheme === 'dark' ? '浅色' : '深色'}
          </Button>
        </div>
      </AppShell.Header>

      <AppShell.Sidebar width={236} label="主导航">
        <Nav aria-label="主导航">
          {NAV.map((g) => (
            <NavGroup key={g.group} label={g.group}>
              {g.items.map((it) => (
                <NavItem
                  key={it.id}
                  icon={<Icon name={it.icon} />}
                  current={page === it.id}
                  onClick={() => setPage(it.id)}
                >
                  {it.text}
                </NavItem>
              ))}
            </NavGroup>
          ))}
        </Nav>
      </AppShell.Sidebar>

      <AppShell.Main>
        <div style={{ display: page === 'overview' ? 'block' : 'none' }}>
          <OverviewPage {...shared} active={page === 'overview'} />
        </div>
        <div style={{ display: page === 'midpoint' ? 'block' : 'none' }}>
          <MidpointPage {...shared} active={page === 'midpoint'} />
        </div>
        <div style={{ display: page === 'stackup' ? 'block' : 'none' }}>
          <StackupPage {...shared} active={page === 'stackup'} />
        </div>
        <div style={{ display: page === 'swap' ? 'block' : 'none' }}>
          <SwapPage {...shared} active={page === 'swap'} />
        </div>
        <div style={{ display: page === 'overwrite' ? 'block' : 'none' }}>
          <OverwritePage {...shared} active={page === 'overwrite'} />
        </div>
        <div style={{ display: page === 'snapshot' ? 'block' : 'none' }}>
          <SnapshotPage {...shared} active={page === 'snapshot'} />
        </div>
      </AppShell.Main>

      <AppShell.Footer>
        <div className={statusError ? 'statusbar statusbar--error' : 'statusbar'}>
          <span className="statusbar__dot" />
          <span className="statusbar__text">{status}</span>
        </div>
      </AppShell.Footer>
    </AppShell>
  )
}
