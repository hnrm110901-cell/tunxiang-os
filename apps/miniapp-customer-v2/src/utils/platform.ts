/**
 * platform.ts — Taro platform detection and adaptation layer
 *
 * Smooths over WeChat (weapp) vs Douyin (tt) vs H5 differences so
 * the rest of the codebase calls one consistent API regardless of platform.
 */

import Taro from '@tarojs/taro'

// ─── Platform detection ───────────────────────────────────────────────────────

export const Platform = {
  isWeChat: process.env.TARO_ENV === 'weapp',
  isDouyin: process.env.TARO_ENV === 'tt',
  isH5:     process.env.TARO_ENV === 'h5',
} as const

// ─── Share ────────────────────────────────────────────────────────────────────

export interface ShareOptions {
  title: string
  path: string
  imageUrl?: string
  desc?: string
}

/**
 * Trigger platform-specific share flow.
 *
 * WeChat  : calls Taro.showShareMenu so the system share button becomes active;
 *           the actual share sheet is driven by onShareAppMessage on the page.
 * Douyin  : calls Taro.shareAppMessage directly (tt supports imperative share).
 * H5      : tries navigator.share (Web Share API), falls back to copy link.
 */
export function shareAppMessage(options: ShareOptions): void {
  if (Platform.isWeChat) {
    Taro.showShareMenu({ withShareTicket: true }).catch(() => {
      // showShareMenu may fail if called outside a user tap — ignore
    })
    // Persist options so the page's onShareAppMessage callback can read them
    ;(globalThis as Record<string, unknown>).__txShareOptions = options
    return
  }

  if (Platform.isDouyin) {
    // Douyin uses the same Taro.shareAppMessage but with slightly different params
    Taro.shareAppMessage({
      title: options.title,
      path: options.path,
      imageUrl: options.imageUrl ?? '',
      desc: options.desc ?? '',
    } as Parameters<typeof Taro.shareAppMessage>[0]).catch(() => {
      // ignore share errors
    })
    return
  }

  // H5 fallback
  if (typeof navigator !== 'undefined' && typeof navigator.share === 'function') {
    navigator
      .share({
        title: options.title,
        text: options.desc ?? options.title,
        url: options.path,
      })
      .catch(() => {
        // User may cancel — not an error
      })
  } else {
    // Copy link as last resort
    copyToClipboard(options.path).catch(() => {
      // ignore
    })
  }
}

// ─── Subscribe message (WeChat only) ─────────────────────────────────────────

/**
 * Request WeChat subscription message permission for the given template IDs.
 * Returns true when the user accepts at least one subscription.
 * Returns false on Douyin / H5 (feature not supported).
 */
export async function requestNotification(templateIds: string[]): Promise<boolean> {
  if (!Platform.isWeChat) {
    return false
  }

  try {
    const res = await Taro.requestSubscribeMessage({
      tmplIds: templateIds,
    })
    // res is an object keyed by templateId with values 'accept' | 'reject' | 'ban'
    return templateIds.some(
      (id) => (res as Record<string, string>)[id] === 'accept',
    )
  } catch (_err) {
    return false
  }
}

// ─── Login ────────────────────────────────────────────────────────────────────

export interface PlatformLoginResult {
  code: string
  platform: 'wechat' | 'douyin'
}

/**
 * Obtain a platform login code to exchange for a server-side JWT.
 *
 * WeChat : Taro.login() → wx.code
 * Douyin : Taro.login() via tt runtime → tt.code
 * H5     : not supported via this function — throw an error so callers can
 *          redirect to an OAuth flow instead.
 */
export async function platformLogin(): Promise<PlatformLoginResult> {
  if (Platform.isH5) {
    throw new Error('H5 login must be handled via OAuth redirect')
  }

  const res = await Taro.login()

  return {
    code: res.code,
    platform: Platform.isDouyin ? 'douyin' : 'wechat',
  }
}

// ─── Pay ──────────────────────────────────────────────────────────────────────

/**
 * Invoke platform payment sheet.
 *
 * WeChat : payParams must contain standard wx.requestPayment fields
 *          (timeStamp, nonceStr, package, signType, paySign).
 * Douyin : payParams must contain tt.pay fields
 *          (orderInfo / tradeNo / appId etc. — Douyin SDK param names differ).
 * H5     : payParams must contain { h5PayUrl: string }; we redirect to it.
 */
export async function platformPay(payParams: Record<string, unknown>): Promise<void> {
  if (Platform.isH5) {
    const h5Url = payParams['h5PayUrl']
    if (typeof h5Url === 'string' && h5Url) {
      window.location.href = h5Url
    } else {
      throw new Error('H5 pay requires payParams.h5PayUrl')
    }
    return
  }

  await Taro.requestPayment(payParams as Parameters<typeof Taro.requestPayment>[0])
}

// ─── Clipboard ────────────────────────────────────────────────────────────────

/**
 * Copy text to clipboard.
 * All mini-program platforms use Taro.setClipboardData.
 * H5 uses navigator.clipboard with a textarea fallback.
 */
export async function copyToClipboard(text: string): Promise<void> {
  if (Platform.isH5) {
    if (
      typeof navigator !== 'undefined' &&
      navigator.clipboard &&
      typeof navigator.clipboard.writeText === 'function'
    ) {
      await navigator.clipboard.writeText(text)
    } else {
      // Legacy fallback
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    return
  }

  await Taro.setClipboardData({ data: text })
}

// ─── Phone call ───────────────────────────────────────────────────────────────

/**
 * Initiate a phone call.
 * Mini-program: Taro.makePhoneCall.
 * H5: tel: URI scheme.
 */
export function makePhoneCall(phone: string): void {
  if (Platform.isH5) {
    window.location.href = `tel:${phone}`
    return
  }

  Taro.makePhoneCall({ phoneNumber: phone }).catch(() => {
    // User may cancel — not an error
  })
}

// ─── Save image to album ──────────────────────────────────────────────────────

/**
 * Save an image (tempFilePath on mini-programs, or a URL on H5) to the device.
 *
 * WeChat / Douyin : Taro.saveImageToPhotosAlbum (prompts for album permission).
 * H5              : creates a temporary <a download> link and clicks it.
 */
export async function saveImage(tempFilePath: string): Promise<void> {
  if (Platform.isH5) {
    const a = document.createElement('a')
    a.href = tempFilePath
    a.download = `tunxiang_${Date.now()}.jpg`
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    return
  }

  await Taro.saveImageToPhotosAlbum({ filePath: tempFilePath })
}

// ─── Open settings ────────────────────────────────────────────────────────────

/**
 * Open the mini-program's permission settings page.
 * H5 has no equivalent — silently does nothing.
 */
export function openSettings(): void {
  if (Platform.isH5) {
    return
  }

  Taro.openSetting({}).catch(() => {
    // ignore errors
  })
}
