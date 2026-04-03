import { useEffect } from 'react'
import { useDidShow } from '@tarojs/taro'
import { trackPageView, trackError } from '../utils/track'

/**
 * Auto page-view tracking hook.
 *
 * Usage:
 * ```ts
 * // In any page component:
 * usePageTrack('menu', { category_id: id })
 * ```
 *
 * - Fires a `page_view` event every time the page becomes visible
 *   (including after the user navigates back), using Taro's `useDidShow`.
 * - Registers a global error handler (via `Taro.onError`) scoped to the
 *   lifetime of the component to capture unhandled JS errors and record
 *   them as `page_error` events.
 *
 * @param pageName  Logical name used as `page_name` in the analytics event.
 * @param extra     Optional extra props merged into the `page_view` payload.
 */
export function usePageTrack(pageName: string, extra?: Record<string, unknown>): void {
  // Fire page_view on every show (covers initial mount and back-navigation)
  useDidShow(() => {
    trackPageView({ page_name: pageName, params: extra })
  })

  // Register an unhandled-error listener for the lifetime of this page
  useEffect(() => {
    // Taro exposes onError / offError on all mini-program environments.
    // In H5 this maps to window.onerror; in weapp/tt it hooks into the
    // miniapp global error callback.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const taroAny = require('@tarojs/taro').default as any

    const handleError = (errorMsg: string): void => {
      trackError({ page: pageName, error_message: errorMsg ?? 'Unknown error' })
    }

    if (typeof taroAny?.onError === 'function') {
      taroAny.onError(handleError)
    }

    return () => {
      if (typeof taroAny?.offError === 'function') {
        taroAny.offError(handleError)
      }
    }
  }, [pageName])
}
