import Taro from '@tarojs/taro'
import { createElement, useState, useEffect, useRef, type JSX } from 'react'
import { Image } from '@tarojs/components'
import { trackError } from './track'

// ---------------------------------------------------------------------------
// LazyImage
// ---------------------------------------------------------------------------

interface LazyImageProps {
  src: string
  width: number
  height: number
  alt?: string
  /** URL shown while the image is not yet in viewport. Defaults to a grey box. */
  placeholder?: string
}

/**
 * Defer image loading until the element enters the viewport using
 * Taro's IntersectionObserver API.  A solid grey placeholder is shown first.
 */
export function LazyImage(props: LazyImageProps): JSX.Element {
  const { src, width, height, alt = '', placeholder } = props
  const [visible, setVisible] = useState(false)
  // A stable string ref-id so IntersectionObserver can target the element
  const idRef = useRef(`lazy-img-${Math.random().toString(36).slice(2, 9)}`)
  const observerRef = useRef<Taro.IntersectionObserver | null>(null)

  useEffect(() => {
    const observer = Taro.createIntersectionObserver(undefined as never, {
      thresholds: [0],
      observeAll: false,
    })

    observerRef.current = observer

    observer.relativeToViewport({ bottom: 100 }).observe(`#${idRef.current}`, (res) => {
      if (res.intersectionRatio > 0) {
        setVisible(true)
        // No need to keep observing once we've loaded the real image
        observer.disconnect()
      }
    })

    return () => {
      observerRef.current?.disconnect()
    }
  }, [])

  // Placeholder: either a provided URL or a transparent 1×1 data URI rendered
  // with a grey background via style
  const placeholderSrc =
    placeholder ||
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQI12NgYGBgAAAABQABXvMqGgAAAABJRU5ErkJggg=='

  return createElement(Image, {
    id: idRef.current,
    src: visible ? src : placeholderSrc,
    style: {
      width: `${width}px`,
      height: `${height}px`,
      backgroundColor: visible ? 'transparent' : '#E0E0E0',
      display: 'block',
    },
    mode: 'aspectFill',
    'aria-label': alt,
  } as Parameters<typeof Image>[0])
}

// ---------------------------------------------------------------------------
// preloadSubpackage
// ---------------------------------------------------------------------------

/**
 * Trigger background preloading of a subpackage so it is ready before the
 * user navigates to it.  Maps to WeChat Mini Program's `loadSubPackage` API.
 */
export function preloadSubpackage(root: string): void {
  // Taro types may not expose loadSubPackage on all environments; use any-cast
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const taroAny = Taro as any
  if (typeof taroAny.loadSubPackage === 'function') {
    taroAny.loadSubPackage({ root }).catch(() => {
      // Silently ignore — preloading is best-effort
    })
  }
}

// ---------------------------------------------------------------------------
// MemCache
// ---------------------------------------------------------------------------

interface CacheEntry<T> {
  value: T
  expiresAt: number
}

const DEFAULT_TTL_SECONDS = 5 * 60 // 5 minutes

const store = new Map<string, CacheEntry<unknown>>()

/**
 * Simple in-memory key/value cache with per-entry TTL.
 *
 * Designed for stable data that is expensive to re-fetch on every render,
 * such as menu categories or member-level config.
 */
export class MemCache {
  static get<T>(key: string): T | null {
    const entry = store.get(key)
    if (!entry) return null
    if (Date.now() > entry.expiresAt) {
      store.delete(key)
      return null
    }
    return entry.value as T
  }

  static set<T>(key: string, value: T, ttlSeconds: number = DEFAULT_TTL_SECONDS): void {
    store.set(key, {
      value,
      expiresAt: Date.now() + ttlSeconds * 1000,
    })
  }

  static invalidate(key: string): void {
    store.delete(key)
  }

  static clear(): void {
    store.clear()
  }
}

// ---------------------------------------------------------------------------
// measurePageLoad
// ---------------------------------------------------------------------------

/**
 * Start a page-load timer.  Call the returned function once data is ready to
 * record the elapsed time via the analytics track module.
 *
 * @param pageName  Logical name of the page being measured.
 * @returns A "stop" function — invoke it after the first meaningful render.
 *
 * @example
 * ```ts
 * const stopTimer = measurePageLoad('menu')
 * await fetchMenuData()
 * stopTimer()  // records page_load_ms to analytics
 * ```
 */
export function measurePageLoad(pageName: string): () => void {
  const start = Date.now()

  return function stop(): void {
    const durationMs = Date.now() - start
    // Import track lazily to avoid circular dependency at module-init time
    // (performance.ts → track.ts → no cycle)
    import('./track')
      .then(({ track }) => {
        track('page_load', { page_name: pageName, duration_ms: durationMs })
      })
      .catch((err: unknown) => {
        // If track import somehow fails, fall back to a console warning
        trackError({
          page: pageName,
          error_message: err instanceof Error ? err.message : 'measurePageLoad track failed',
        })
      })
  }
}
