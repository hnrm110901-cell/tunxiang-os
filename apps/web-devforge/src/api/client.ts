import axios, { AxiosError, AxiosInstance } from 'axios'

/** DevForge 后端 base URL（开发期通过 vite proxy 转发到 localhost:8017） */
const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

function getTenantId(): string {
  return localStorage.getItem('devforge.tenantId') || 'demo-tenant'
}

function getEnv(): string {
  return localStorage.getItem('devforge.env') || 'dev'
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
