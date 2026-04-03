/**
 * useAuth — WeChat login → JWT flow
 *
 * Flow:
 *   wx.login() → code → POST /api/v1/auth/wx-login { code, tenant_id }
 *   → { token, refresh_token, user_id, openid }
 *   → persist via Taro.setStorageSync
 *   → sync useUserStore
 *
 * On 401 from any API: txRequest already clears storage + redirects, but
 * consumers can also call requireLogin() to gate any action.
 */

import { useState, useCallback, useEffect } from 'react'
import Taro from '@tarojs/taro'
import { txRequest, TxRequestError } from '../utils/request'
import { setToken, clearAuth, getToken, getTenantId } from '../utils/auth'
import { useUserStore } from '../store/useUserStore'

// ─── Types ────────────────────────────────────────────────────────────────────

interface WxLoginResponse {
  token: string
  refresh_token: string
  user_id: string
  openid: string
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAuth() {
  const setUser = useUserStore((s) => s.setUser)
  const clearUser = useUserStore((s) => s.logout)
  const storeIsLoggedIn = useUserStore((s) => s.isLoggedIn)
  const storeUserId = useUserStore((s) => s.userId)

  const [isLoggedIn, setIsLoggedIn] = useState<boolean>(storeIsLoggedIn)
  const [userId, setUserId] = useState<string>(storeUserId)

  // Keep local state in sync if the store updates from elsewhere
  useEffect(() => {
    setIsLoggedIn(storeIsLoggedIn)
    setUserId(storeUserId)
  }, [storeIsLoggedIn, storeUserId])

  /**
   * Returns true when a non-empty token exists in storage.
   * Does not validate the token with the server.
   */
  const checkLogin = useCallback((): boolean => {
    return getToken().length > 0
  }, [])

  /**
   * Full WeChat login flow.
   * Throws on wx.login failure or API error.
   */
  const login = useCallback(async (): Promise<void> => {
    // 1. Get wx code
    let code: string
    try {
      const res = await Taro.login()
      code = res.code
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'wx.login failed'
      throw new Error(`WeChat login failed: ${msg}`)
    }

    // 2. Exchange code for JWT
    const tenantId = getTenantId()
    const data = await txRequest<WxLoginResponse>(
      '/api/v1/auth/wx-login',
      'POST',
      { code, tenant_id: tenantId },
    )

    // 3. Persist credentials
    setToken(data.token, data.refresh_token)
    try {
      Taro.setStorageSync('tx_user_id', data.user_id)
      Taro.setStorageSync('tx_openid', data.openid)
    } catch (_e) {
      // storage errors must not crash the login flow
    }

    // 4. Sync store
    setUser({ userId: data.user_id, openId: data.openid })

    // 5. Update local state
    setIsLoggedIn(true)
    setUserId(data.user_id)
  }, [setUser])

  /**
   * Clears all auth state (storage + store + local state).
   */
  const logout = useCallback((): void => {
    clearAuth()
    clearUser()
    setIsLoggedIn(false)
    setUserId('')
  }, [clearUser])

  /**
   * Runs `callback` immediately if the user is logged in;
   * otherwise triggers the full login flow first, then runs callback on success.
   */
  const requireLogin = useCallback(
    (callback: () => void): void => {
      if (checkLogin()) {
        callback()
        return
      }
      login()
        .then(() => {
          callback()
        })
        .catch((err: unknown) => {
          // Surface login errors via Taro toast so the UI always gets feedback
          const msg =
            err instanceof TxRequestError
              ? err.message
              : err instanceof Error
              ? err.message
              : 'Login failed'
          Taro.showToast({ title: msg, icon: 'none', duration: 2000 }).catch(() => {
            // ignore toast errors
          })
        })
    },
    [checkLogin, login],
  )

  return {
    login,
    logout,
    checkLogin,
    isLoggedIn,
    userId,
    requireLogin,
  }
}
