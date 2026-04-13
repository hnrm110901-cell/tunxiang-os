/**
 * format.ts — presentation helpers
 *
 * Currency amounts throughout the system are stored in fen (分, integer cents).
 * Dates arrive as ISO-8601 strings from the API.
 *
 * NOTE: fenToYuan / fenToYuanDisplay 与 @tunxiang/design-system 的 formatPrice
 * 功能一致。Web端请用 formatPrice，小程序端继续用本文件的函数。
 */

/**
 * 分转元（不带¥前缀）
 * @example fenToYuan(1250) => "12.50"
 */
export function fenToYuan(fen: number): string {
  if (!Number.isFinite(fen)) return '0.00'
  return (fen / 100).toFixed(2)
}

/**
 * 分转元（带¥前缀），等价于 @tx-ds/utils 的 formatPrice
 * @example fenToYuanDisplay(1250) => "¥12.50"
 */
export function fenToYuanDisplay(fen: number): string {
  return `¥${fenToYuan(fen)}`
}

/**
 * formatPrice 别名 — 与 @tunxiang/design-system 保持接口一致
 * 小程序端无法直接引用 @tx-ds/utils，因此在本文件提供同名函数
 */
export function formatPrice(fen: number): string {
  return fenToYuanDisplay(fen)
}

/**
 * Formats an ISO-8601 date string to "MM-DD HH:mm" local time.
 * @example formatDate("2026-04-02T14:30:00Z") => "04-02 14:30"
 */
export function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso

  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')

  return `${mm}-${dd} ${hh}:${min}`
}

/**
 * Masks the middle four digits of a phone number.
 * @example formatPhone("13812348888") => "138****8888"
 */
export function formatPhone(phone: string): string {
  if (!phone || phone.length < 7) return phone
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`
}

/**
 * Truncates a string to at most `len` characters, appending "…" when cut.
 * @example truncate("你好世界", 3) => "你好世…"
 */
export function truncate(str: string, len: number): string {
  if (!str) return ''
  if (len <= 0) return ''
  if (str.length <= len) return str
  return str.slice(0, len) + '…'
}
