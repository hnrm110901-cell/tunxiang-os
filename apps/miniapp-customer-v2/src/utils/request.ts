import Taro from '@tarojs/taro'

/** Unified API response envelope from tx-* services */
export interface TxApiResponse<T = unknown> {
  ok: boolean
  data: T
  error?: {
    code: string
    message: string
  }
}

/** Error thrown by txRequest on ok=false or network failure */
export class TxRequestError extends Error {
  public readonly code: string
  public readonly httpStatus?: number

  constructor(code: string, message: string, httpStatus?: number) {
    super(message)
    this.name = 'TxRequestError'
    this.code = code
    this.httpStatus = httpStatus
  }
}

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

/**
 * Unified request wrapper using Taro.request.
 * - Auto-injects X-Tenant-ID and Authorization headers.
 * - Returns response.data.data when ok=true.
 * - Throws TxRequestError when ok=false.
 * - On HTTP 401: clears auth storage and redirects to /pages/login/index.
 */
export async function txRequest<T = unknown>(
  path: string,
  method: HttpMethod = 'GET',
  data?: Record<string, unknown> | unknown[] | null,
): Promise<T> {
  const token = Taro.getStorageSync<string>('tx_token') ?? ''
  const tenantId = Taro.getStorageSync<string>('tx_tenant_id') ?? ''
  const apiBase =
    (Taro.getStorageSync<string>('tx_api_base') as string) || 'http://localhost:8000'

  const url = `${apiBase.replace(/\/$/, '')}${path}`

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Tenant-ID': tenantId,
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  let res: Taro.request.SuccessCallbackResult<TxApiResponse<T>>

  try {
    res = await Taro.request<TxApiResponse<T>>({
      url,
      method,
      data: data ?? undefined,
      header: headers,
      timeout: 15000,
    })
  } catch (err: unknown) {
    // Network-level failure (no response received)
    const msg = err instanceof Error ? err.message : 'Network error'
    throw new TxRequestError('NETWORK_ERROR', msg)
  }

  const { statusCode, data: body } = res

  // Handle 401 – clear credentials and bounce to login
  if (statusCode === 401) {
    Taro.removeStorageSync('tx_token')
    Taro.removeStorageSync('tx_refresh_token')
    Taro.removeStorageSync('tx_tenant_id')
    Taro.redirectTo({ url: '/pages/login/index' }).catch(() => {
      // ignore redirect errors (e.g. already on login page)
    })
    throw new TxRequestError('UNAUTHORIZED', 'Session expired, please login again', 401)
  }

  // Non-2xx without a structured body
  if (statusCode < 200 || statusCode >= 300) {
    const code = body?.error?.code ?? `HTTP_${statusCode}`
    const message = body?.error?.message ?? `Request failed with status ${statusCode}`
    throw new TxRequestError(code, message, statusCode)
  }

  // Structured error from service even on 2xx
  if (!body.ok) {
    const code = body.error?.code ?? 'SERVICE_ERROR'
    const message = body.error?.message ?? 'An unknown service error occurred'
    throw new TxRequestError(code, message, statusCode)
  }

  return body.data
}
