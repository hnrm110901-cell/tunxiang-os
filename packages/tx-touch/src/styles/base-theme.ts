/**
 * @tx/touch · base-theme — Store 终端（POS / KDS / Crew）暗色主题 Token 对象
 *
 * @deprecated v1.0 起优先使用 `@tx/tokens` CSS Variables（`var(--tx-primary)` 等）
 * 本文件保留是为兼容历史 inline-style 写法。新代码请走 CSS Variables 通道。
 *
 * ⚠️ 已知 drift（与 v1.0 宪法 docs/ui-ux-constitution-v1.md §3.2 不一致）：
 *   - success:  #27AE60 → 宪法值 #0F6E56
 *   - warning:  #F2994A → 宪法值 #BA7517
 *   - danger:   #EB5757 → 宪法值 #A32D2D
 *   - info:     #2D9CDB → 宪法值 #185FA5
 * 任何新引用本文件 `TX.success/warning/danger/info` 的代码必须先把上述四色对齐到宪法值。
 *
 * 历史用法：
 *   import { TX, BTN, INPUT } from '@tx/touch';
 *   <button style={{ ...BTN.base, ...BTN.primary }}>确认</button>
 *
 * 推荐替代：
 *   import '@tx/tokens/tokens.css';
 *   <button className="tx-btn tx-btn-primary">确认</button>
 */

// ─── 语义色（暗色主题） ──────────────────────────────────────────────────────────

const TX = {
  // 背景层级
  bg:         '#0B1A20',   // 主背景
  card:       '#112B36',   // 卡片/浮层
  raised:     '#0D2029',   // raised surface
  nav:        '#0D1E28',   // 导航/侧栏

  // 边框/分割线
  border:     'rgba(255,255,255,0.08)',
  divider:    'rgba(255,255,255,0.06)',

  // 文字
  text:       'rgba(255,255,255,0.92)',   // 主文字
  text2:      'rgba(255,255,255,0.65)',   // 次要文字
  text3:      'rgba(255,255,255,0.38)',   // 辅助/禁用文字

  // 品牌/功能色
  accent:     '#FF6B35',   // 品牌主色（暖橙）— 与宪法一致
  accentH:    '#E55A28',   // hover
  success:    '#27AE60',   // ⚠️ drift，宪法值 #0F6E56
  danger:     '#EB5757',   // ⚠️ drift，宪法值 #A32D2D
  warning:    '#F2994A',   // ⚠️ drift，宪法值 #BA7517
  info:       '#2D9CDB',   // ⚠️ drift，宪法值 #185FA5
  white:      '#FFFFFF',

  // 状态色
  pending:    '#faad14',
  confirmed:  '#27AE60',
  seated:     '#2D9CDB',
  cancelled:  '#EB5757',
  noShow:     '#8C8C8C',
} as const;

// ─── 排版 ──────────────────────────────────────────────────────────────────────

const TXT = {
  title:    { fontSize: 22, fontWeight: 700, color: TX.text } as React.CSSProperties,
  heading:  { fontSize: 18, fontWeight: 700, color: TX.text } as React.CSSProperties,
  body:     { fontSize: 15, fontWeight: 400, color: TX.text } as React.CSSProperties,
  caption:  { fontSize: 13, fontWeight: 400, color: TX.text2 } as React.CSSProperties,
  small:    { fontSize: 12, fontWeight: 400, color: TX.text3 } as React.CSSProperties,
};

// ─── 按钮（≥44px 触控目标） ─────────────────────────────────────────────────────

const BTN = {
  /** 基础按钮样式 — 所有按钮的起点 */
  base: {
    height: 44,
    minWidth: 44,
    borderRadius: 8,
    border: 'none',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    padding: '0 20px',
    transition: 'background 0.15s, opacity 0.15s',
    boxSizing: 'border-box',
  } as React.CSSProperties,

  primary: {
    background: TX.accent,
    color: TX.white,
  } as React.CSSProperties,

  secondary: {
    background: 'rgba(255,255,255,0.08)',
    color: TX.text,
  } as React.CSSProperties,

  success: {
    background: TX.success,
    color: TX.white,
  } as React.CSSProperties,

  danger: {
    background: TX.danger,
    color: TX.white,
  } as React.CSSProperties,

  ghost: {
    background: 'transparent',
    color: TX.text2,
    border: '1px solid rgba(255,255,255,0.12)',
  } as React.CSSProperties,

  /** 大按钮（主要 CTA） */
  lg: {
    height: 48,
    fontSize: 16,
    borderRadius: 10,
    padding: '0 28px',
  } as React.CSSProperties,

  /** 小按钮（仅图标 / 紧凑场景，仍≥44px 垂直空间） */
  sm: {
    height: 44,
    minWidth: 44,
    fontSize: 13,
    padding: '0 14px',
    borderRadius: 6,
  } as React.CSSProperties,

  /** 图标圆形按钮 */
  icon: {
    width: 44,
    height: 44,
    borderRadius: '50%',
    padding: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  } as React.CSSProperties,
};

// ─── 输入框（≥44px） ─────────────────────────────────────────────────────────────

const INPUT = {
  base: {
    width: '100%',
    height: 44,
    padding: '0 14px',
    borderRadius: 8,
    border: `1px solid ${TX.border}`,
    background: 'rgba(255,255,255,0.06)',
    color: TX.text,
    fontSize: 15,
    outline: 'none',
    boxSizing: 'border-box',
  } as React.CSSProperties,

  textarea: {
    width: '100%',
    minHeight: 80,
    padding: 12,
    borderRadius: 8,
    border: `1px solid ${TX.border}`,
    background: 'rgba(255,255,255,0.06)',
    color: TX.text,
    fontSize: 15,
    outline: 'none',
    resize: 'vertical',
    boxSizing: 'border-box',
    fontFamily: 'inherit',
  } as React.CSSProperties,

  select: {
    width: '100%',
    height: 44,
    padding: '0 14px',
    borderRadius: 8,
    border: `1px solid ${TX.border}`,
    background: 'rgba(255,255,255,0.06)',
    color: TX.text,
    fontSize: 15,
    outline: 'none',
    boxSizing: 'border-box' as React.CSSProperties['boxSizing'],
    WebkitAppearance: 'none' as React.CSSProperties['WebkitAppearance'],
  } as React.CSSProperties,
};

// ─── 标签/状态徽标 ───────────────────────────────────────────────────────────────

const TAG = {
  base: {
    padding: '3px 12px',
    borderRadius: 10,
    fontSize: 12,
    fontWeight: 600,
    whiteSpace: 'nowrap',
    display: 'inline-flex',
    alignItems: 'center',
  } as React.CSSProperties,

  status: (color: string): React.CSSProperties => ({
    padding: '3px 12px',
    borderRadius: 10,
    fontSize: 12,
    fontWeight: 600,
    whiteSpace: 'nowrap',
    background: color + '22',
    color: color,
  }),
};

// ─── 布局 ──────────────────────────────────────────────────────────────────────

const LAYOUT = {
  /** 全屏页面 */
  fullPage: {
    background: TX.bg,
    minHeight: '100vh',
    color: TX.text,
    fontFamily: 'Noto Sans SC, sans-serif',
  } as React.CSSProperties,

  /** 内容区域的页内 padding */
  contentPadding: { padding: 24 } as React.CSSProperties,

  /** 居中空状态 */
  empty: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    color: TX.text3,
    gap: 12,
    padding: 40,
  } as React.CSSProperties,
};

// ─── 导出 ──────────────────────────────────────────────────────────────────────

export { TX, TXT, BTN, INPUT, TAG, LAYOUT };
