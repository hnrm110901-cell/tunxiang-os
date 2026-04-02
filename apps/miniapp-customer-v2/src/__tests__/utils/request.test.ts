/**
 * txRequest unit tests
 *
 * Taro.request is mocked at the module level via setup.ts / __mocks__/taro.ts.
 * Each test overrides the mock return/rejection to exercise a specific path.
 */

import Taro from '@tarojs/taro'
import { txRequest, TxRequestError } from '../../utils/request'

// Typed shorthand
const mockRequest = Taro.request as jest.Mock
const mockGetStorage = Taro.getStorageSync as jest.Mock
const mockRemoveStorage = Taro.removeStorageSync as jest.Mock
const mockRedirectTo = Taro.redirectTo as jest.Mock

// ─── helpers ─────────────────────────────────────────────────────────────────

/** Build a fake Taro.request success response */
function makeOkResponse<T>(data: T, statusCode = 200) {
  return Promise.resolve({
    statusCode,
    data: { ok: true, data },
    header: {},
    cookies: [],
    errMsg: 'request:ok',
  })
}

function makeErrorResponse(code: string, message: string, statusCode = 200) {
  return Promise.resolve({
    statusCode,
    data: { ok: false, error: { code, message } },
    header: {},
    cookies: [],
    errMsg: 'request:ok',
  })
}

function makeHttpErrorResponse(statusCode: number) {
  return Promise.resolve({
    statusCode,
    data: { ok: false, error: { code: `HTTP_${statusCode}`, message: `Error ${statusCode}` } },
    header: {},
    cookies: [],
    errMsg: `request:fail ${statusCode}`,
  })
}

// ─── tests ───────────────────────────────────────────────────────────────────

describe('txRequest', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    // Default: no token, no tenant, no custom base
    mockGetStorage.mockReturnValue('')
  })

  // ── Success path ───────────────────────────────────────────────────────────

  it('returns the data field from an ok=true response', async () => {
    const payload = { orderId: 'ord-001', status: 'paid' }
    mockRequest.mockReturnValueOnce(makeOkResponse(payload))

    const result = await txRequest('/api/v1/orders/ord-001')

    expect(result).toEqual(payload)
  })

  it('passes method and body to Taro.request', async () => {
    mockRequest.mockReturnValueOnce(makeOkResponse({}))
    const body = { storeId: 'store-1', items: [] }

    await txRequest('/api/v1/orders/cart', 'POST', body)

    expect(mockRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'POST',
        data: body,
      }),
    )
  })

  // ── Header injection ───────────────────────────────────────────────────────

  it('always injects X-Tenant-ID header', async () => {
    mockGetStorage.mockImplementation((key: string) => {
      if (key === 'tx_tenant_id') return 'tenant-xyz'
      return ''
    })
    mockRequest.mockReturnValueOnce(makeOkResponse({}))

    await txRequest('/api/v1/orders')

    const callArgs = mockRequest.mock.calls[0][0] as { header: Record<string, string> }
    expect(callArgs.header['X-Tenant-ID']).toBe('tenant-xyz')
  })

  it('injects Authorization header when token is present', async () => {
    mockGetStorage.mockImplementation((key: string) => {
      if (key === 'tx_token') return 'jwt-abc123'
      return ''
    })
    mockRequest.mockReturnValueOnce(makeOkResponse({}))

    await txRequest('/api/v1/orders')

    const callArgs = mockRequest.mock.calls[0][0] as { header: Record<string, string> }
    expect(callArgs.header['Authorization']).toBe('Bearer jwt-abc123')
  })

  it('omits the Authorization header when no token is stored', async () => {
    mockGetStorage.mockReturnValue('')
    mockRequest.mockReturnValueOnce(makeOkResponse({}))

    await txRequest('/api/v1/orders')

    const callArgs = mockRequest.mock.calls[0][0] as { header: Record<string, string> }
    expect(callArgs.header['Authorization']).toBeUndefined()
  })

  it('constructs the URL from the stored tx_api_base', async () => {
    mockGetStorage.mockImplementation((key: string) => {
      if (key === 'tx_api_base') return 'https://api.tunxiang.com'
      return ''
    })
    mockRequest.mockReturnValueOnce(makeOkResponse({}))

    await txRequest('/api/v1/menu')

    const callArgs = mockRequest.mock.calls[0][0] as { url: string }
    expect(callArgs.url).toBe('https://api.tunxiang.com/api/v1/menu')
  })

  it('falls back to localhost:8000 when tx_api_base is not set', async () => {
    mockGetStorage.mockReturnValue('')
    mockRequest.mockReturnValueOnce(makeOkResponse({}))

    await txRequest('/api/v1/menu')

    const callArgs = mockRequest.mock.calls[0][0] as { url: string }
    expect(callArgs.url).toContain('localhost:8000')
  })

  // ── API-level errors (ok=false) ────────────────────────────────────────────

  it('throws TxRequestError with code and message when ok=false', async () => {
    mockRequest.mockReturnValueOnce(
      makeErrorResponse('DISH_NOT_FOUND', 'The requested dish does not exist'),
    )

    await expect(txRequest('/api/v1/dishes/999')).rejects.toMatchObject({
      name: 'TxRequestError',
      code: 'DISH_NOT_FOUND',
      message: 'The requested dish does not exist',
    })
  })

  it('uses SERVICE_ERROR code when ok=false response has no error object', async () => {
    mockRequest.mockReturnValueOnce(
      Promise.resolve({
        statusCode: 200,
        data: { ok: false },
        header: {},
        cookies: [],
        errMsg: 'request:ok',
      }),
    )

    await expect(txRequest('/api/v1/orders')).rejects.toMatchObject({
      code: 'SERVICE_ERROR',
    })
  })

  // ── HTTP 401 ───────────────────────────────────────────────────────────────

  it('calls removeStorageSync for all auth keys on 401 before throwing', async () => {
    mockRequest.mockReturnValueOnce(makeHttpErrorResponse(401))

    await expect(txRequest('/api/v1/orders')).rejects.toMatchObject({
      code: 'UNAUTHORIZED',
      httpStatus: 401,
    })

    expect(mockRemoveStorage).toHaveBeenCalledWith('tx_token')
    expect(mockRemoveStorage).toHaveBeenCalledWith('tx_refresh_token')
    expect(mockRemoveStorage).toHaveBeenCalledWith('tx_tenant_id')
  })

  it('calls redirectTo to the login page on 401', async () => {
    mockRequest.mockReturnValueOnce(makeHttpErrorResponse(401))

    await expect(txRequest('/api/v1/orders')).rejects.toThrow()

    expect(mockRedirectTo).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/pages/login/index' }),
    )
  })

  // ── Non-2xx HTTP errors ────────────────────────────────────────────────────

  it('throws TxRequestError for non-2xx status codes', async () => {
    mockRequest.mockReturnValueOnce(makeHttpErrorResponse(500))

    await expect(txRequest('/api/v1/orders')).rejects.toMatchObject({
      name: 'TxRequestError',
      httpStatus: 500,
    })
  })

  it('uses structured error body when available on non-2xx', async () => {
    mockRequest.mockReturnValueOnce(
      Promise.resolve({
        statusCode: 422,
        data: { ok: false, error: { code: 'VALIDATION_ERROR', message: 'Invalid input' } },
        header: {},
        cookies: [],
        errMsg: '',
      }),
    )

    await expect(txRequest('/api/v1/orders', 'POST', {})).rejects.toMatchObject({
      code: 'VALIDATION_ERROR',
      message: 'Invalid input',
      httpStatus: 422,
    })
  })

  // ── Network errors ─────────────────────────────────────────────────────────

  it('throws TxRequestError with NETWORK_ERROR code on network failure', async () => {
    mockRequest.mockRejectedValueOnce(new Error('Network timeout'))

    await expect(txRequest('/api/v1/orders')).rejects.toMatchObject({
      name: 'TxRequestError',
      code: 'NETWORK_ERROR',
      message: 'Network timeout',
    })
  })

  it('uses generic "Network error" message when rejection is not an Error instance', async () => {
    mockRequest.mockRejectedValueOnce('connection refused')

    await expect(txRequest('/api/v1/orders')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      message: 'Network error',
    })
  })

  // ── TxRequestError class ──────────────────────────────────────────────────

  describe('TxRequestError', () => {
    it('exposes code, message, and httpStatus', () => {
      const err = new TxRequestError('MY_CODE', 'Something went wrong', 403)
      expect(err.name).toBe('TxRequestError')
      expect(err.code).toBe('MY_CODE')
      expect(err.message).toBe('Something went wrong')
      expect(err.httpStatus).toBe(403)
    })

    it('is an instance of Error', () => {
      const err = new TxRequestError('X', 'msg')
      expect(err).toBeInstanceOf(Error)
    })

    it('httpStatus is undefined when not provided', () => {
      const err = new TxRequestError('X', 'msg')
      expect(err.httpStatus).toBeUndefined()
    })
  })
})
