export const txColors = {
  primary: '#FF6B35',
  primaryHover: '#FF8555',
  primaryActive: '#E55A28',
  primaryLight: '#FFF3ED',
  navy: '#1E2A3A',
  navyLight: '#2C3E50',
  success: '#0F6E56',
  successLight: '#E8F5F0',
  warning: '#BA7517',
  warningLight: '#FEF3E2',
  danger: '#A32D2D',
  dangerLight: '#FDEAEA',
  info: '#185FA5',
  infoLight: '#E8F0FB',
  text1: '#2C2C2A',
  text2: '#5F5E5A',
  text3: '#B4B2A9',
  bg1: '#FFFFFF',
  bg2: '#F8F7F5',
  bg3: '#F0EDE6',
  border: '#E8E6E1',
} as const;

export const txRadius = {
  xs: 4, sm: 8, md: 12, lg: 16, xl: 24, full: 9999
} as const;

export const txSpacing = {
  1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 8: 32, 10: 40, 12: 48
} as const;

export const txFontSize = {
  admin: { h1: 24, h2: 20, h3: 16, body: 14, caption: 12 },
  store: { h1: 32, h2: 24, h3: 20, body: 18, caption: 16, kdsTimer: 32 },
} as const;

export const txTapTarget = {
  min: 48, rec: 56, lg: 72, gap: 12
} as const;

// 业务语义映射
export const txBusinessColors = {
  // 毛利率颜色
  marginGood: txColors.success,        // >= 阈值
  marginWarn: txColors.warning,        // < 阈值 且 >= 80%
  marginBad: txColors.danger,          // < 80%阈值

  // 出餐时间颜色
  timeGood: txColors.success,          // 剩余 > 50%
  timeWarn: txColors.warning,          // 剩余 <= 50%
  timeOver: txColors.danger,           // 已超时

  // 库存颜色
  stockNormal: 'transparent',          // 充足
  stockLow: txColors.warning,          // 低于安全线
  stockOut: txColors.danger,           // 沽清

  // Agent预警颜色
  agentInfo: txColors.info,
  agentWarning: txColors.warning,
  agentCritical: txColors.danger,
} as const;
