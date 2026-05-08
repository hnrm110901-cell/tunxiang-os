/**
 * Storybook Preview — 全局装饰 + 视口预设
 *
 * 注入屯象 Design Tokens（@tx/tokens/tokens.css）+ tx-touch 重置/动画/聚焦样式，
 * 让所有 stories 渲染环境与生产 Store 终端一致。
 */
import type { Preview } from '@storybook/react';
import '@tx/tokens/tokens.css';
import '../src/styles/reset.css';
import '../src/styles/animations.css';
import '../src/styles/focus.css';

/** 屯象 Store 终端触控视口（宪法 §2.2-2.4） */
const TX_VIEWPORTS = {
  /** 商米 T2 安卓 POS — 800×1280 竖屏 */
  shangmiT2Portrait: {
    name: '商米 T2 (POS 竖屏)',
    styles: { width: '800px', height: '1280px' },
    type: 'tablet',
  },
  /** 商米 T2 横屏（KDS 替代视口） */
  shangmiT2Landscape: {
    name: '商米 T2 (POS 横屏)',
    styles: { width: '1280px', height: '800px' },
    type: 'tablet',
  },
  /** iPad Pro 11 — 高端店升级 */
  ipadPro11: {
    name: 'iPad Pro 11 (高端 POS)',
    styles: { width: '1194px', height: '834px' },
    type: 'tablet',
  },
  /** 商米 D2 KDS 屏 */
  kdsScreen: {
    name: '商米 D2 (KDS 出餐屏)',
    styles: { width: '1280px', height: '800px' },
    type: 'tablet',
  },
  /** 员工手机 (Crew PWA) */
  crewMobile: {
    name: '员工手机 (Crew PWA)',
    styles: { width: '414px', height: '896px' },
    type: 'mobile',
  },
};

const preview: Preview = {
  parameters: {
    actions: { argTypesRegex: '^on[A-Z].*' },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    backgrounds: {
      default: 'POS Dark',
      values: [
        { name: 'POS Dark', value: '#0D1117' },
        { name: 'POS Light', value: '#F8F7F5' },
        { name: 'KDS Dark', value: '#0B1117' },
      ],
    },
    viewport: {
      viewports: TX_VIEWPORTS,
      defaultViewport: 'shangmiT2Portrait',
    },
    a11y: {
      // 宪法 §7：触控目标 ≥ 48px、对比度 ≥ 4.5:1、focus 可见
      config: {
        rules: [
          { id: 'color-contrast', enabled: true },
          { id: 'target-size', enabled: true },
        ],
      },
    },
  },
};

export default preview;
