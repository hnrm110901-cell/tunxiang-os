// Brand color palette
export const colors = {
  // Primary brand
  brand: '#FF6B2C',
  brandDark: '#E55A1C',
  brandLight: '#FF8F5E',

  // Background layers
  appBg: '#0B1A20',
  cardBg: '#132029',
  surfaceBg: '#1A2E38',

  // Text
  textPrimary: '#FFFFFF',
  textSecondary: '#9EB5C0',
  textDisabled: '#4A6572',
  textInverse: '#0B1A20',

  // Status
  success: '#34C759',
  warning: '#FF9F0A',
  error: '#FF3B30',
  info: '#0A84FF',

  // Border
  borderDefault: '#1E3340',
  borderStrong: '#2A4558',

  // Overlay
  overlay: 'rgba(0, 0, 0, 0.6)',
  overlayLight: 'rgba(0, 0, 0, 0.3)',
} as const

// Spacing scale (in px, will be converted by pxtransform)
export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  '2xl': 48,
  '3xl': 64,
} as const

// Border radius
export const radius = {
  sm: 4,
  md: 8,
  lg: 12,
  xl: 16,
  '2xl': 24,
  full: 9999,
} as const

// Font sizes (in px)
export const fontSize = {
  xs: 20,
  sm: 24,
  base: 28,
  md: 32,
  lg: 36,
  xl: 40,
  '2xl': 48,
  '3xl': 56,
} as const

// Font weights
export const fontWeight = {
  normal: '400',
  medium: '500',
  semibold: '600',
  bold: '700',
} as const

// Z-index layers
export const zIndex = {
  base: 0,
  raised: 10,
  dropdown: 100,
  sticky: 200,
  overlay: 300,
  modal: 400,
  toast: 500,
} as const

export type ColorKey = keyof typeof colors
export type SpacingKey = keyof typeof spacing
export type RadiusKey = keyof typeof radius
