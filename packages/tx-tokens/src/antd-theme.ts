import { txColors, txRadius } from './tokens';

// 注：tx-tokens 不直接依赖 antd（保持 zero-dep 稳态）。
// ThemeConfig 由消费方（web-admin / web-hub 等）的 antd 版本结构兼容；
// 这里使用结构化类型避免循环依赖。
type ThemeConfig = {
  token?: Record<string, unknown>;
  components?: Record<string, Record<string, unknown>>;
  algorithm?: unknown;
  cssVar?: unknown;
  hashed?: boolean;
};

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
