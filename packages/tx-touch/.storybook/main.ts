/**
 * Storybook 主配置 — packages/tx-touch
 *
 * 屯象OS UI 设计宪法 §6.4：
 *   - tx-touch 视觉回归 + 设计审查 单一可信源
 *   - Vite 模式（与 web-pos / web-kds 构建栈一致）
 *   - viewport addon 提供 POS / KDS / Mobile 触控视口预设
 */
import type { StorybookConfig } from '@storybook/react-vite';

const config: StorybookConfig = {
  stories: [
    '../src/components/**/*.stories.@(ts|tsx|mdx)',
    '../src/**/*.docs.mdx',
  ],
  addons: [
    '@storybook/addon-essentials', // viewport / controls / actions / docs
    '@storybook/addon-a11y',       // a11y 检查（宪法 §7 联动）
  ],
  framework: {
    name: '@storybook/react-vite',
    options: {},
  },
  docs: {
    autodocs: 'tag',
  },
  typescript: {
    reactDocgen: 'react-docgen-typescript',
  },
};

export default config;
