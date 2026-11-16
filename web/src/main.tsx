import React from 'react'
import ReactDOM from 'react-dom/client'

import 'oink-ui/styles.css'
import './app.css'

import App from './App'
import { API_BASE } from './api'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

// 启动诊断：把「页面从哪加载的 / 后端地址 / 外壳是否渲染」报给本地后端，
// 后端写到 %TEMP%\altium_diag.json —— 无界面环境下排查桌面版问题用。
window.setTimeout(() => {
  const info = {
    href: location.href,
    apiBase: API_BASE || '(同源)',
    injected: (window as any).__ALTUM_API__ ?? null,
    shell: !!document.querySelector('.ok-shell'),
    nav: !!document.querySelector('.ok-nav__item'),
    body: (document.body?.innerText || '').slice(0, 200),
    ua: navigator.userAgent,
  }
  fetch(`${API_BASE}/api/debug`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(info),
  }).catch(() => {
    /* 诊断上报失败不影响主流程 */
  })
}, 1500)
