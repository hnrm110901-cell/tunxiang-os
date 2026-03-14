/**
 * 屯象OS · 间距Token
 * 基于 TunxiangOS UI Design Spec v1.0
 * 基准: 8pt Grid — 所有间距是4的倍数
 */

export const spacing = {
  1:  4,    // --space-xs: icon-to-text, badge padding
  2:  8,    // --space-sm: compact list, inline gap
  3:  12,   // --space-md: card padding (mobile)
  4:  16,   // --space-lg: card padding (PC/tablet)
  5:  24,   // --space-xl: page section gap
  6:  32,
  7:  40,
  8:  48,
  9:  64,
  10: 80,
  11: 96,
  12: 128,
} as const;

// 栅格断点
export const breakpoint = {
  mobile:  767,
  tablet:  1279,
  desktop: 1280,
} as const;

// 固定布局尺寸（Design Spec v1.0）
export const layout = {
  topbarHeight:    56,    // 规范: 56px (was 52)
  railWidth:       56,
  sidebarWidth:    220,
  aiPanelWidth:    320,
  drawerWidth:     400,
  bottomTabHeight: 56,
  maxContentWidth: 1200,  // 规范: max 1200px centered
} as const;
