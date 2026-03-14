/**
 * 屯象OS · Ant Design 主题覆盖
 * 基于 TunxiangOS UI Design Spec v1.0
 */
import { theme as antdTheme } from 'antd';
import type { ThemeConfig } from 'antd';

const fontFamily = "'PingFang SC', 'HarmonyOS Sans SC', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif";

// 亮色主题
export const lightTheme: ThemeConfig = {
  token: {
    colorPrimary:      '#FF6B35',  // brand-500
    colorSuccess:      '#27AE60',  // success
    colorWarning:      '#F2994A',  // warning
    colorError:        '#EB5757',  // danger
    colorInfo:         '#2D9CDB',  // info
    colorBgContainer:  '#FFFFFF',
    colorBgLayout:     '#FAFAFA',
    colorText:         '#1E2A3A',  // navy-700
    colorTextSecondary:'#595959',
    colorBorder:       '#E8E8E8',
    borderRadius: 8,
    fontSize: 14,
    fontFamily,
  },
  components: {
    Layout: {
      headerBg: '#FFFFFF',
      bodyBg: '#FAFAFA',
      siderBg: '#1A1A2E',
    },
    Menu: {
      darkItemBg: '#1A1A2E',
      darkItemSelectedBg: '#FF6B35',
    },
    Card: { borderRadiusLG: 12 },
    Button: { borderRadius: 8, controlHeight: 36 },
    Input: { borderRadius: 8, controlHeight: 36 },
    Table: { borderRadius: 8 },
  },
};

// 暗色主题
export const darkTheme: ThemeConfig = {
  token: {
    colorPrimary:      '#FF6B35',
    colorSuccess:      '#34D399',
    colorWarning:      '#FBBF24',
    colorError:        '#F87171',
    colorInfo:         '#60A5FA',
    colorBgContainer:  '#1A2332',  // dark-raised
    colorBgLayout:     '#0F1419',  // dark-bg
    colorText:         'rgba(255,255,255,0.92)',
    colorTextSecondary:'rgba(255,255,255,0.50)',
    colorBorder:       'rgba(255,255,255,0.10)',
    borderRadius: 8,
    fontSize: 14,
    fontFamily,
    colorBgBase: '#0F1419',
    colorTextBase: 'rgba(255,255,255,0.92)',
  },
  components: {
    Layout: {
      headerBg: '#0F1419',
      bodyBg: '#0F1419',
      siderBg: '#0F1419',
    },
    Menu: {
      darkItemBg: '#0F1419',
      darkItemSelectedBg: '#FF6B35',
    },
    Card: { borderRadiusLG: 12 },
    Button: { borderRadius: 8, controlHeight: 36 },
    Input: { borderRadius: 8, controlHeight: 36 },
    Table: { borderRadius: 8 },
  },
  algorithm: antdTheme.darkAlgorithm,
};
