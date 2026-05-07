/**
 * Ant Design 5.x 主题配置 — 屯象OS Admin
 * 通过 ConfigProvider 注入，不硬编码颜色
 */
import type { ThemeConfig } from 'antd';
import { txColors } from '@tx/tokens';

export const txAdminTheme: ThemeConfig = {
  token: {
    colorPrimary: txColors.primary,
    colorSuccess: txColors.success,
    colorWarning: txColors.warning,
    colorError: txColors.danger,
    colorInfo: txColors.info,
    colorTextBase: '#2C2C2A',
    colorBgBase: '#FFFFFF',
    borderRadius: 6,
    fontSize: 14,
  },
  components: {
    Layout: { headerBg: txColors.navy, siderBg: txColors.navy },
    Menu: { darkItemBg: txColors.navy, darkItemSelectedBg: txColors.primary },
    Table: { headerBg: '#F8F7F5' },
  },
};

export default txAdminTheme;
