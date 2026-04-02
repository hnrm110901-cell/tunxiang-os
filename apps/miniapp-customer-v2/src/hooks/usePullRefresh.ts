/**
 * usePullRefresh — consistent pull-to-refresh wrapper
 *
 * Wraps the provided async fetch function with:
 *   - Taro.usePullDownRefresh() listener to start refresh on pull
 *   - Taro.stopPullDownRefresh() call after fetch completes (or fails)
 *   - isRefreshing state for manual trigger (e.g. a "Refresh" button)
 *   - onRefresh() for programmatic / button-triggered refresh
 *
 * Usage:
 *   const { isRefreshing, onRefresh } = useRefresh(fetchData)
 *
 * The page must have enablePullDownRefresh: true in its page config.
 */

import { useState, useCallback } from 'react'
import Taro, { usePullDownRefresh } from '@tarojs/taro'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface UseRefreshResult {
  isRefreshing: boolean
  onRefresh: () => Promise<void>
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useRefresh(fetchFn: () => Promise<void>): UseRefreshResult {
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false)

  const onRefresh = useCallback(async (): Promise<void> => {
    // Guard against concurrent refreshes
    if (isRefreshing) return

    setIsRefreshing(true)

    try {
      await fetchFn()
    } catch (_err: unknown) {
      // Errors are the caller's responsibility to surface (via their own state).
      // usePullRefresh only manages the loading indicator lifecycle.
    } finally {
      setIsRefreshing(false)

      // Always stop the native pull-down animation regardless of success/failure.
      // Taro.stopPullDownRefresh is safe to call even if pull wasn't triggered
      // via the native gesture (e.g. called from a button).
      try {
        Taro.stopPullDownRefresh()
      } catch (_e) {
        // stopPullDownRefresh can fail in H5 environment; ignore safely
      }
    }
  }, [fetchFn, isRefreshing])

  // Bind to the WeChat miniapp native pull-down gesture
  usePullDownRefresh(() => {
    onRefresh().catch(() => {
      // onRefresh already handles errors internally
    })
  })

  return {
    isRefreshing,
    onRefresh,
  }
}
