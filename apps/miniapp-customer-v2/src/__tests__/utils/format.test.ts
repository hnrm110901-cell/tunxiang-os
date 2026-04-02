/**
 * format.ts unit tests
 *
 * All functions are pure — no mocks needed.
 */

import {
  fenToYuan,
  fenToYuanDisplay,
  formatDate,
  formatPhone,
  truncate,
} from '../../utils/format'

// ─── fenToYuan ────────────────────────────────────────────────────────────────

describe('fenToYuan', () => {
  it('returns "0.00" for 0 fen', () => {
    expect(fenToYuan(0)).toBe('0.00')
  })

  it('returns "1.00" for 100 fen', () => {
    expect(fenToYuan(100)).toBe('1.00')
  })

  it('returns "12.50" for 1250 fen', () => {
    expect(fenToYuan(1250)).toBe('12.50')
  })

  it('returns "0.01" for 1 fen', () => {
    expect(fenToYuan(1)).toBe('0.01')
  })

  it('always produces exactly two decimal places', () => {
    // 10 fen = 0.10 — must not be "0.1"
    expect(fenToYuan(10)).toBe('0.10')
  })

  it('handles large amounts correctly', () => {
    expect(fenToYuan(99999)).toBe('999.99')
    expect(fenToYuan(1000000)).toBe('10000.00')
  })

  it('returns "0.00" for non-finite inputs', () => {
    expect(fenToYuan(NaN)).toBe('0.00')
    expect(fenToYuan(Infinity)).toBe('0.00')
    expect(fenToYuan(-Infinity)).toBe('0.00')
  })

  it('handles negative fen (refunds / credits)', () => {
    expect(fenToYuan(-500)).toBe('-5.00')
  })
})

// ─── fenToYuanDisplay ────────────────────────────────────────────────────────

describe('fenToYuanDisplay', () => {
  it('prepends ¥ to the decimal string', () => {
    expect(fenToYuanDisplay(1250)).toBe('¥12.50')
  })

  it('works for 0 fen', () => {
    expect(fenToYuanDisplay(0)).toBe('¥0.00')
  })

  it('works for 100 fen (¥1.00)', () => {
    expect(fenToYuanDisplay(100)).toBe('¥1.00')
  })

  it('formats large amounts with the ¥ prefix', () => {
    expect(fenToYuanDisplay(999900)).toBe('¥9999.00')
  })
})

// ─── formatPhone ─────────────────────────────────────────────────────────────

describe('formatPhone', () => {
  it('masks the middle four digits of an 11-digit mobile number', () => {
    expect(formatPhone('13812345678')).toBe('138****5678')
  })

  it('always shows the first 3 and last 4 characters', () => {
    expect(formatPhone('18611112222')).toBe('186****2222')
  })

  it('returns the original string unchanged if it is shorter than 7 characters', () => {
    expect(formatPhone('12345')).toBe('12345')
    expect(formatPhone('123456')).toBe('123456')
  })

  it('returns the original value when phone is an empty string', () => {
    expect(formatPhone('')).toBe('')
  })

  it('works for 7-character edge case', () => {
    // slice(0,3) = "138", slice(-4) = "5678" — only 7 chars total so barely qualifies
    expect(formatPhone('1385678')).toBe('138****5678')
  })
})

// ─── truncate ────────────────────────────────────────────────────────────────

describe('truncate', () => {
  it('appends … when the string exceeds len', () => {
    expect(truncate('hello world', 5)).toBe('hello…')
  })

  it('returns the string unchanged when it fits exactly within len', () => {
    expect(truncate('hello', 5)).toBe('hello')
  })

  it('returns the string unchanged when shorter than len', () => {
    expect(truncate('hi', 5)).toBe('hi')
  })

  it('returns an empty string for an empty input', () => {
    expect(truncate('', 5)).toBe('')
  })

  it('returns an empty string when len is 0', () => {
    expect(truncate('hello', 0)).toBe('')
  })

  it('works with Chinese characters (each is 1 JS char)', () => {
    expect(truncate('你好世界朋友', 4)).toBe('你好世界…')
  })

  it('works correctly when len is negative', () => {
    // len ≤ 0 — always return ''
    expect(truncate('hello', -1)).toBe('')
  })
})

// ─── formatDate ──────────────────────────────────────────────────────────────

describe('formatDate', () => {
  it('returns empty string for an empty input', () => {
    expect(formatDate('')).toBe('')
  })

  it('returns the original string when it is not a valid ISO date', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })

  it('formats a valid ISO-8601 string to MM-DD HH:mm in local time', () => {
    // Construct a date object at a known local time to avoid TZ sensitivity
    const d = new Date(2026, 3, 2, 14, 30) // April 2 2026 14:30 local
    const iso = d.toISOString()
    const result = formatDate(iso)
    // Verify structure — local month/day/hour/minute
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const min = String(d.getMinutes()).padStart(2, '0')
    expect(result).toBe(`${mm}-${dd} ${hh}:${min}`)
  })
})
