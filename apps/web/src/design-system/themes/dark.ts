/**
 * 屯象OS · Dark Theme Token Map
 * 基于 TunxiangOS UI Design Spec v1.0
 * 深色主题：Navy调暗色 (#0F1419)
 */
import { brand, dark as darkColors, semantic } from '../tokens/colors';

export const darkTheme = {
  // Backgrounds
  '--tx-bg':              darkColors.bg,
  '--tx-bg-primary':      darkColors.bg,
  '--tx-bg-secondary':    darkColors.raised,
  '--tx-bg-tertiary':     darkColors.sidebar,
  '--tx-bg-elevated':     darkColors.raised,

  // Text
  '--tx-text-primary':    darkColors.t1,
  '--tx-text-secondary':  darkColors.t2,
  '--tx-text-tertiary':   darkColors.t3,
  '--tx-text-disabled':   darkColors.t4,

  // Border
  '--tx-border':          'rgba(255,255,255,0.10)',
  '--tx-border-light':    darkColors.border,
  '--tx-divider':         darkColors.border,

  // Accent (Brand Orange, brighter in dark)
  '--tx-accent':          brand[500],     // #FF6B35
  '--tx-accent-hover':    brand[400],     // #FF7E4A
  '--tx-accent-active':   brand[300],     // #FF9A6E
  '--tx-accent-soft':     'rgba(255,107,53,0.15)',
  '--tx-accent-bg':       'rgba(255,107,53,0.10)',

  // Semantic (brighter in dark for contrast)
  '--tx-success':         '#34D399',
  '--tx-warning':         '#FBBF24',
  '--tx-danger':          '#F87171',
  '--tx-info':            '#60A5FA',

  // Warm
  '--tx-sun':             '#FFC244',
  '--tx-fire':            '#FF9B6A',
  '--tx-amber':           '#FFB86C',

  // Surface
  '--tx-surface':         darkColors.raised,
  '--tx-surface-hover':   '#243447',

  // Shadows (darker in dark mode)
  '--tx-shadow-sm':       '0 1px 2px rgba(0,0,0,0.2)',
  '--tx-shadow-md':       '0 2px 8px rgba(0,0,0,0.3)',
  '--tx-shadow-lg':       '0 4px 16px rgba(0,0,0,0.4)',
  '--tx-shadow-xl':       '0 8px 24px rgba(0,0,0,0.5)',

  // Chart
  '--tx-chart-grid':      'rgba(255,255,255,0.06)',
  '--tx-chart-axis':      'rgba(255,255,255,0.25)',
  '--tx-chart-tooltip-bg': darkColors.raised,
} as const;
