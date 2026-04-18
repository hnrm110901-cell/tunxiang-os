/**
 * 屯象OS · Light Theme Token Map
 * v2 设计系统 — 浅色备选主题（暖橙 #FF6B35 主色）
 */
import { brand, neutral, semantic, warm, navy } from '../tokens/colors';

export const lightTheme = {
  // Backgrounds
  '--tx-bg':              neutral[50],
  '--tx-bg-primary':      neutral[0],
  '--tx-bg-secondary':    neutral[50],
  '--tx-bg-tertiary':     neutral[100],
  '--tx-bg-elevated':     neutral[0],

  // Text (Navy heading hierarchy)
  '--tx-text-primary':    navy[700],      // #1E2A3A
  '--tx-text-secondary':  neutral[600],
  '--tx-text-tertiary':   neutral[400],
  '--tx-text-disabled':   neutral[300],

  // Border
  '--tx-border':          neutral[200],
  '--tx-border-light':    neutral[100],
  '--tx-divider':         neutral[100],

  // Accent (暖橙 #FF6B35)
  '--tx-accent':          brand[500],     // #FF6B35
  '--tx-accent-hover':    brand[600],     // #E55A28
  '--tx-accent-active':   brand[700],     // #CC4A1A
  '--tx-accent-soft':     'rgba(255,107,53,0.08)',
  '--tx-accent-bg':       brand[50],      // #FFF3ED

  // Semantic
  '--tx-success':         semantic.success,
  '--tx-warning':         semantic.warning,
  '--tx-danger':          semantic.danger,
  '--tx-info':            semantic.info,

  // Warm
  '--tx-sun':             warm.sun,
  '--tx-fire':            warm.fire,
  '--tx-amber':           warm.amber,

  // Surface
  '--tx-surface':         neutral[0],
  '--tx-surface-hover':   neutral[100],

  // Shadows
  '--tx-shadow-sm':       '0 1px 3px rgba(30,42,58,0.06)',
  '--tx-shadow-md':       '0 2px 8px rgba(30,42,58,0.08)',
  '--tx-shadow-lg':       '0 4px 16px rgba(30,42,58,0.10)',
  '--tx-shadow-xl':       '0 8px 24px rgba(30,42,58,0.12)',

  // Chart
  '--tx-chart-grid':      neutral[100],
  '--tx-chart-axis':      neutral[400],
  '--tx-chart-tooltip-bg': neutral[0],
} as const;
