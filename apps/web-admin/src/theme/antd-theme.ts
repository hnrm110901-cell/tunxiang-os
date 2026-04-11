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
    colorBorder: '#E8E6E1',
    borderRadius: 6,
    borderRadiusSM: 4,
    borderRadiusLG: 8,
    fontSize: 14,
    fontSizeHeading1: 24,
    fontSizeHeading2: 20,
    fontSizeHeading3: 16,
    lineHeight: 1.571,
    controlHeight: 36,
    controlHeightSM: 28,
    controlHeightLG: 44,
  },
  components: {
    Layout: {
      headerBg: '#1E2A3A',
      siderBg: '#1E2A3A',
      bodyBg: '#F8F7F5',
    },
    Menu: {
      darkItemBg: '#1E2A3A',
      darkItemSelectedBg: '#FF6B35',
      darkItemHoverBg: 'rgba(255, 107, 53, 0.15)',
      darkSubMenuItemBg: '#141E2A',
    },
    Table: {
      headerBg: '#F8F7F5',
      headerColor: '#2C2C2A',
      rowHoverBg: '#FFF3ED',
    },
  },
};
