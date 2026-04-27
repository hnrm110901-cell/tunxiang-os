import type { Config } from 'tailwindcss'

/**
 * Tailwind 与 AntD v5 共存：用 Tailwind 写工具类布局，AntD 提供组件 + theme token。
 * preflight 关闭以避免与 AntD 的 reset.css / global.css 冲突。
 */
const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        // 与 src/styles/theme.ts 的 AntD theme token 对齐
        brand: {
          DEFAULT: '#D97706', // amber-600
          dark: '#B45309',
        },
        slate: {
          950: '#020617',
        },
      },
      fontFamily: {
        mono: ['SF Mono', 'JetBrains Mono', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}

export default config
