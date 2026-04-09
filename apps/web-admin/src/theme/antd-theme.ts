/**
 * Ant Design 5.x 主题配置 — 屯象OS Admin
 * 通过 ConfigProvider 注入，不硬编码颜色
 */
import type { ThemeConfig } from 'antd';

export const txAdminTheme: ThemeConfig = {
  token: {
    colorPrimary: '#FF6B35',
    colorSuccess: '#0F6E56',
    colorWarning: '#BA7517',
    colorError: '#A32D2D',
    colorInfo: '#185FA5',
    colorTextBase: '#2C2C2A',
    colorBgBase: '#FFFFFF',
    borderRadius: 6,
    fontSize: 14,
  },
  components: {
    Layout: { headerBg: '#1E2A3A', siderBg: '#1E2A3A' },
    Menu: { darkItemBg: '#1E2A3A', darkItemSelectedBg: '#FF6B35' },
    Table: { headerBg: '#F8F7F5' },
  },
};

export default txAdminTheme;
