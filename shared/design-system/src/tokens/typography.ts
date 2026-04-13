/**
 * 屯象OS · 字体Token
 * 基于 TunxiangOS UI Design Spec v1.0
 * 中文: PingFang SC, HarmonyOS Sans SC
 * 英文: DM Sans, Inter
 * 数字: DIN Alternate (tabular)
 * 等宽: JetBrains Mono
 */

// ── Font Families ──
export const fontFamily = {
  sans:  "'PingFang SC', 'HarmonyOS Sans SC', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif",
  serif: "'Noto Serif SC', 'STSong', Georgia, serif",
  ui:    "'DM Sans', 'Inter', 'SF Pro Display', -apple-system, system-ui, sans-serif",
  mono:  "'JetBrains Mono', 'Fira Code', monospace",
  number: "'DIN Alternate', 'DIN Next', 'Tabular Lining', 'DM Sans', sans-serif",
} as const;

// ── Type Scale (Design Spec v1.0) ──
export const fontSize = {
  '2xs': 11,   // Tiny — badge text, tooltips
  xs:    12,   // Caption — column headers, timestamps
  sm:    14,   // Body — default text, table cells
  md:    16,   // H3 — card title
  lg:    18,   // H2 — section heading
  xl:    22,   // H1 — page heading, modal title
  '2xl': 28,   // Display — dashboard page title, KPI value
  '3xl': 56,   // Hero — not commonly used
} as const;

// ── Line Heights (Design Spec v1.0) ──
export const lineHeight = {
  tight:   1.2,   // Display, KPI
  snug:    1.375, // H1-H3
  base:    1.5,   // Body
  relaxed: 1.571, // Caption (22/14)
  loose:   2.0,
} as const;

// ── Letter Spacing ──
export const letterSpacing = {
  tight:   '-0.02em',
  normal:  '0em',
  wide:    '0.04em',
  wider:   '0.08em',
  widest:  '0.16em',
} as const;

// ── Preset Styles (mapped to Design Spec v1.0 typography scale) ──
export const typography = {
  display:  { fontSize: fontSize['2xl'], fontWeight: 500, lineHeight: lineHeight.tight },
  hero:     { fontSize: fontSize['3xl'], fontWeight: 700, lineHeight: lineHeight.tight },
  title1:   { fontSize: fontSize.xl,     fontWeight: 500, lineHeight: lineHeight.snug },
  title2:   { fontSize: fontSize.lg,     fontWeight: 500, lineHeight: lineHeight.snug },
  title3:   { fontSize: fontSize.md,     fontWeight: 500, lineHeight: lineHeight.snug },
  body:     { fontSize: fontSize.sm,     fontWeight: 400, lineHeight: lineHeight.base },
  caption:  { fontSize: fontSize.xs,     fontWeight: 400, lineHeight: lineHeight.relaxed },
  overline: { fontSize: fontSize['2xs'], fontWeight: 600, lineHeight: lineHeight.tight, letterSpacing: letterSpacing.widest, textTransform: 'uppercase' as const },
  kpiValue: { fontSize: fontSize['2xl'], fontWeight: 700, lineHeight: lineHeight.tight },
  fontStack: fontFamily.sans,
} as const;
