import type { ThemeConfig } from 'antd';
import { txColors, txRadius } from './tokens';

export const txAdminTheme: ThemeConfig = {
  token: {
    colorPrimary: txColors.primary,
    colorSuccess: txColors.success,
    colorWarning: txColors.warning,
    colorError: txColors.danger,
    colorInfo: txColors.info,
    colorTextBase: txColors.text1,
    colorBgBase: txColors.bg1,
    colorBorder: txColors.border,
    borderRadius: txRadius.xs + 2,   // 6px
    borderRadiusSM: txRadius.xs,     // 4px
    borderRadiusLG: txRadius.sm,     // 8px
    fontSize: 14,
    fontSizeHeading1: 24,
    fontSizeHeading2: 20,
    fontSizeHeading3: 16,
    fontSizeHeading4: 14,
    lineHeight: 1.571,
    controlHeight: 36,
    controlHeightSM: 28,
    controlHeightLG: 44,
  },
  components: {
    Layout: {
      headerBg: txColors.navy,
      siderBg: txColors.navy,
      bodyBg: txColors.bg2,
    },
    Menu: {
      darkItemBg: txColors.navy,
      darkItemSelectedBg: txColors.primary,
      darkItemHoverBg: 'rgba(255, 107, 53, 0.15)',
      darkSubMenuItemBg: '#141E2A',
    },
    Table: {
      headerBg: txColors.bg2,
      headerColor: txColors.text1,
      rowHoverBg: txColors.primaryLight,
    },
    Button: {
      primaryColor: '#FFFFFF',
      defaultBorderColor: txColors.border,
    },
    Card: {
      headerBg: txColors.bg2,
    },
  },
};

// ProComponents 扩展配置（给 web-admin ProLayout 使用）
export const txProLayoutToken = {
  siderMenuType: 'sub' as const,
  colorMenuBackground: txColors.navy,
  colorMenuItemDivider: 'rgba(255,255,255,0.08)',
  colorTextMenuTitle: '#FFFFFF',
  colorTextMenu: 'rgba(255,255,255,0.75)',
  colorTextMenuSelected: '#FFFFFF',
  colorBgMenuItemSelected: txColors.primary,
  colorBgMenuItemHover: 'rgba(255, 107, 53, 0.15)',
  colorTextMenuActive: '#FFFFFF',
};
