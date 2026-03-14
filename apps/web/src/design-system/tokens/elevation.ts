/**
 * 屯象OS · 阴影/圆角/z-index Token
 * 基于 TunxiangOS UI Design Spec v1.0
 */

// ── Border Radius (Design Spec v1.0) ──
export const radius = {
  '2xs':  3,
  xs:     4,     // --radius-sm: badge, small tag
  sm:     6,
  md:     8,     // --radius-md: button, input, table row hover
  lg:     12,    // --radius-lg: card, modal, dropdown
  xl:     16,    // --radius-xl: bottom sheet (mobile), floating panel
  '2xl':  24,
  full:   9999,
} as const;

// ── Elevation Shadows ──
export const shadow = {
  0: 'none',
  1: '0 1px 2px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)',
  2: '0 2px 8px rgba(0,0,0,0.07), 0 1px 4px rgba(0,0,0,0.04)',
  3: '0 4px 16px rgba(0,0,0,0.08), 0 2px 8px rgba(0,0,0,0.04)',
  4: '0 8px 32px rgba(0,0,0,0.10), 0 4px 12px rgba(0,0,0,0.05)',
} as const;

// ── Z-index ──
export const zIndex = {
  base:    0,
  raised:  10,
  overlay: 100,
  modal:   200,
  toast:   300,
} as const;

// ── Motion ──
export const motion = {
  fast:   '100ms ease-in',
  normal: '200ms ease-out',
  slow:   '400ms ease',
  spring: '300ms cubic-bezier(0.34,1.56,0.64,1)',
} as const;
