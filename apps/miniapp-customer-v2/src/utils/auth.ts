import Taro from '@tarojs/taro'

const KEY_TOKEN = 'tx_token'
const KEY_REFRESH_TOKEN = 'tx_refresh_token'
const KEY_TENANT_ID = 'tx_tenant_id'

/**
 * Returns the current access token or an empty string if not set.
 */
export function getToken(): string {
  return Taro.getStorageSync<string>(KEY_TOKEN) ?? ''
}

/**
 * Persists access token and refresh token to storage.
 */
export function setToken(token: string, refreshToken: string): void {
  Taro.setStorageSync(KEY_TOKEN, token)
  Taro.setStorageSync(KEY_REFRESH_TOKEN, refreshToken)
}

/**
 * Clears all auth-related keys from storage.
 */
export function clearAuth(): void {
  Taro.removeStorageSync(KEY_TOKEN)
  Taro.removeStorageSync(KEY_REFRESH_TOKEN)
  Taro.removeStorageSync(KEY_TENANT_ID)
}

/**
 * Returns the current tenant ID or an empty string if not set.
 */
export function getTenantId(): string {
  return Taro.getStorageSync<string>(KEY_TENANT_ID) ?? ''
}

/**
 * Returns true if a non-empty token is present in storage.
 */
export function isLoggedIn(): boolean {
  const token = getToken()
  return token.length > 0
}
