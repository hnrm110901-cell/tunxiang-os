import type { ThemeConfig } from 'antd'
import { theme as antdTheme } from 'antd'

/** 屯象 DevForge 设计 Token（暗色主题 + 品牌橙） */
export const COLORS = {
  slate900: '#0F172A',   // 主色（深色底）
  slate800: '#1E293B',
  slate700: '#334155',
  slate200: '#E2E8F0',
  amber600: '#D97706',   // 屯=粮仓暖橙（品牌色）
  amber500: '#F59E0B',
  blue: '#2563EB',       // 信息
  green: '#16A34A',      // 成功
  yellow: '#EAB308',     // 警告
  red: '#DC2626',        // 失败 / 生产环境
} as const

/** AntD v5 暗色主题配置 */
export const themeConfig: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: COLORS.amber600,
    colorInfo: COLORS.blue,
    colorSuccess: COLORS.green,
    colorWarning: COLORS.yellow,
    colorError: COLORS.red,
    colorBgBase: COLORS.slate900,
    colorBgContainer: COLORS.slate800,
    colorBgElevated: COLORS.slate800,
    colorBgLayout: COLORS.slate900,
    colorBorder: COLORS.slate700,
    borderRadius: 6,
    fontFamily:
      'Inter, "PingFang SC", "Source Han Sans CN", "Noto Sans SC", system-ui, -apple-system, sans-serif',
    fontFamilyCode: '"SF Mono", "JetBrains Mono", Menlo, Consolas, monospace',
  },
  components: {
    Layout: {
      siderBg: COLORS.slate900,
      headerBg: COLORS.slate900,
      bodyBg: COLORS.slate900,
      headerHeight: 56,
    },
    Menu: {
      darkItemBg: COLORS.slate900,
      darkItemSelectedBg: COLORS.amber600,
      darkSubMenuItemBg: COLORS.slate900,
    },
    Table: {
      headerBg: COLORS.slate800,
    },
  },
}
