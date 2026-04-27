import axios, { AxiosError, AxiosInstance } from 'axios'

import { useEnvStore } from '../stores/env'

/** DevForge 后端 base URL（开发期通过 vite proxy 转发到 localhost:8017） */
const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

/**
 * 演示用固定 UUID（all-zero）。后端 TenantMiddleware 强制 UUID 格式，
 * 字符串字面量（如 'demo-tenant'）会被 401 拒绝，导致首次访问页面无法 bootstrap。
 * 生产环境必须由 SSO 登录后注入真实 tenant UUID 到 localStorage。
 */
const DEMO_TENANT_UUID = '00000000-0000-0000-0000-000000000000'

function getTenantId(): string {
  const stored = localStorage.getItem('devforge.tenantId')?.trim()
  // 仅当 localStorage 中有值且像 UUID 时才使用，否则回退到 demo UUID
  if (stored && /^[0-9a-f-]{36}$/i.test(stored)) {
    return stored
  }
  return DEMO_TENANT_UUID
}

function getEnv(): string {
  // 直接从 zustand store 读取原始字符串值；
  // 不能读 localStorage('devforge.env')——persist 中间件存的是 JSON 信封 {state:{currentEnv:'dev'}}。
  return useEnvStore.getState().currentEnv
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 15_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

apiClient.interceptors.request.use((config) => {
  config.headers.set('X-Tenant-ID', getTenantId())
  config.headers.set('X-Devforge-Env', getEnv())
  return config
})

apiClient.interceptors.response.use(
  (resp) => resp,
  (err: AxiosError) => {
    // 统一日志，业务层用 try/catch 或 React Query 的 onError 处理
    console.warn('[DevForge API]', err.config?.url, err.message)
    return Promise.reject(err)
  },
)

/** 标准响应格式 { ok, data, error } */
export interface ApiResponse<T> {
  ok: boolean
  data: T
  error?: { code: string; message: string }
}
