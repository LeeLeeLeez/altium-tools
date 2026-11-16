/**
 * HTTP 客户端。
 *
 * - 浏览器 / vite dev：同源 `/api/*`（dev 由 Vite 代理到 http://127.0.0.1:8765）
 * - Tauri 桌面版：Rust 侧在页面脚本之前注入 `window.__ALTUM_API__`
 *   （形如 http://127.0.0.1:8765），此时前端与后端跨源，由后端放行 CORS。
 */

declare global {
  interface Window {
    __ALTUM_API__?: string
  }
}

const BASE = (typeof window !== 'undefined' && window.__ALTUM_API__) || ''

/** 当前使用的后端地址（空 = 同源）。 */
export const API_BASE = BASE

export class ApiError extends Error {
  status: number
  hint?: string
  constructor(status: number, message: string, hint?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.hint = hint
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (e) {
    throw new ApiError(0, `无法连接本地服务：${(e as Error).message}`)
  }
  const text = await res.text()
  let data: any = {}
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { error: text.slice(0, 400) }
    }
  }
  if (!res.ok || data?.ok === false) {
    throw new ApiError(res.status, data?.error || `请求失败（${res.status}）`, data?.hint)
  }
  return data as T
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) }),
}

/** 把异常转成一句人话（带桥接超时的处置提示）。 */
export function errText(e: unknown): string {
  if (e instanceof ApiError) return e.hint ? `${e.message}\n${e.hint}` : e.message
  if (e instanceof Error) return e.message
  return String(e)
}
