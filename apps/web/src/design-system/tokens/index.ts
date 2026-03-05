/**
 * 智链OS Design Tokens
 * 规范来源：前后端重构_产品研发开发规范_V1.0 第三章
 *
 * 使用方式：
 *   import { tokens } from '@/design-system/tokens';
 *   // 或在 CSS Modules 中直接用 var(--accent) 等 CSS 变量
 */

// ── CSS 变量注入（在 main.tsx 中调用 injectTokens()）─────────────────────────
export function injectTokens() {
  const root = document.documentElement;

  // 判断当前主题
  const isDark = root.classList.contains('dark');

  const vars: Record<string, string> = isDark ? {
    '--bg':             '#000000',
    '--surface':        '#1C1C1E',
    '--surface-hover':  '#2C2C2E',
    '--text-primary':   '#F5F5F7',
    '--text-secondary': '#AEAEB2',
    '--text-tertiary':  '#636366',
    '--border':         'rgba(255,255,255,0.08)',
    '--accent':         '#FF6B2C',
    '--accent-soft':    'rgba(255,107,44,0.15)',
    '--green':          '#30D158',
    '--red':            '#FF453A',
    '--yellow':         '#FFD60A',
    '--blue':           '#0A84FF',
  } : {
    '--bg':             '#F5F5F7',
    '--surface':        '#FFFFFF',
    '--surface-hover':  '#FAFAFA',
    '--text-primary':   '#1D1D1F',
    '--text-secondary': '#6E6E73',
    '--text-tertiary':  '#AEAEB2',
    '--border':         'rgba(0,0,0,0.06)',
    '--accent':         '#FF6B2C',
    '--accent-soft':    'rgba(255,107,44,0.08)',
    '--green':          '#34C759',
    '--red':            '#FF3B30',
    '--yellow':         '#FF9F0A',
    '--blue':           '#007AFF',
  };

  // 间距与圆角（与主题无关）
  const staticVars: Record<string, string> = {
    '--radius-sm':   '10px',
    '--radius-md':   '14px',
    '--radius-lg':   '20px',
    '--radius-xl':   '28px',
    '--radius-full': '9999px',
    '--shadow-sm':   '0 1px 2px rgba(0,0,0,0.04)',
    '--shadow-md':   '0 4px 12px rgba(0,0,0,0.06)',
    '--shadow-lg':   '0 8px 32px rgba(0,0,0,0.08)',
  };

  Object.entries({ ...vars, ...staticVars }).forEach(([k, v]) => {
    root.style.setProperty(k, v);
  });
}

// ── TypeScript 常量（供 JS 逻辑使用）────────────────────────────────────────
export const colors = {
  accent:  '#FF6B2C',
  green:   '#34C759',
  red:     '#FF3B30',
  yellow:  '#FF9F0A',
  blue:    '#007AFF',
} as const;

export const typography = {
  display:  { fontSize: 48, fontWeight: 700, lineHeight: 1.0 },
  title1:   { fontSize: 28, fontWeight: 700, lineHeight: 1.2 },
  title2:   { fontSize: 20, fontWeight: 600, lineHeight: 1.3 },
  body:     { fontSize: 15, fontWeight: 400, lineHeight: 1.5 },
  caption:  { fontSize: 13, fontWeight: 500, lineHeight: 1.4 },
  overline: { fontSize: 12, fontWeight: 600, lineHeight: 1.2, letterSpacing: '0.5px', textTransform: 'uppercase' as const },
  fontStack: "'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Helvetica Neue', sans-serif",
} as const;

export const motion = {
  cardHover:  'transform 200ms ease-out, box-shadow 200ms ease-out',
  cardActive: 'transform 100ms ease-in',
  pageIn:     'opacity 400ms ease, transform 400ms ease',
} as const;
