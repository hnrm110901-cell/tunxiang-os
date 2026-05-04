/**
 * 屯象OS · KDS 高对比主题
 * 纯黑背景 + 超大字号 + 时间三色灯
 * KDS 零品牌色原则 — 不出现暖橙
 */
export const kdsTheme = {
  // 纯黑背景（最高对比度）
  '--tx-bg':              '#000000',
  '--tx-bg-primary':      '#000000',
  '--tx-bg-secondary':    '#111111',
  '--tx-bg-tertiary':     '#1A1A1A',
  '--tx-bg-elevated':     '#1A1A1A',

  // 高对比文字
  '--tx-text-primary':    '#FFFFFF',
  '--tx-text-secondary':  'rgba(255,255,255,0.75)',
  '--tx-text-tertiary':   'rgba(255,255,255,0.50)',
  '--tx-text-disabled':   'rgba(255,255,255,0.25)',

  // 边框
  '--tx-border':          'rgba(255,255,255,0.15)',
  '--tx-border-light':    'rgba(255,255,255,0.08)',
  '--tx-divider':         'rgba(255,255,255,0.10)',

  // KDS 时间色标（行业标准三色灯）
  '--tx-kds-green':       '#22C55E',   // < 5分钟：正常
  '--tx-kds-amber':       '#F59E0B',   // 5-10分钟：警告
  '--tx-kds-red':         '#EF4444',   // > 10分钟：超时

  // 中性 accent（KDS 零品牌色原则 — 不出现暖橙）
  '--tx-accent':          '#888888',
  '--tx-accent-hover':    '#AAAAAA',
  '--tx-accent-active':   '#CCCCCC',
  '--tx-accent-soft':     'rgba(255,255,255,0.10)',
  '--tx-accent-bg':       'rgba(255,255,255,0.05)',

  // 语义色（KDS高亮度版本）
  '--tx-success':         '#22C55E',
  '--tx-warning':         '#F59E0B',
  '--tx-danger':          '#EF4444',
  '--tx-info':            '#3B82F6',

  // Warm (high-contrast for KDS)
  '--tx-sun':             '#FFD566',
  '--tx-fire':            '#FFB088',
  '--tx-amber':           '#FFCC80',

  // Surface
  '--tx-surface':         '#111111',
  '--tx-surface-hover':   '#1F1F1F',

  // Chart (high-contrast for KDS)
  '--tx-chart-grid':      'rgba(255,255,255,0.10)',
  '--tx-chart-axis':      'rgba(255,255,255,0.40)',
  '--tx-chart-tooltip-bg': '#1A1A1A',

  // Shadows (minimal for KDS)
  '--tx-shadow-sm':       '0 1px 2px rgba(0,0,0,0.5)',
  '--tx-shadow-md':       '0 2px 8px rgba(0,0,0,0.6)',
  '--tx-shadow-lg':       '0 4px 16px rgba(0,0,0,0.7)',
  '--tx-shadow-xl':       '0 8px 24px rgba(0,0,0,0.8)',
} as const;
