/**
 * Figma → 屯象OS Design Token 同步配置
 *
 * 使用方式:
 *   1. 在 Figma 中使用 "Variables" 面板定义所有 Token
 *   2. 通过 Figma REST API (GET /v1/files/:file_key/variables/local) 拉取
 *   3. 运行 `npx ts-node shared/design-tokens/figma-sync.ts` 生成各终端格式
 *
 * Token 命名规范 (Figma 变量名 → 代码变量名):
 *   brand/primary     → --tx-primary
 *   brand/primary-hover → --tx-primary-hover
 *   semantic/success   → --tx-success
 *   neutral/text-1     → --tx-text-1
 */

export interface FigmaSyncConfig {
  /** Figma 文件 Key（从 URL 提取） */
  fileKey: string;
  /** Figma Personal Access Token（环境变量注入，禁止硬编码） */
  accessToken: string;
  /** 要拉取的 Variable Collection 名称 */
  collections: string[];
  /** 输出目标 */
  outputs: OutputTarget[];
}

export interface OutputTarget {
  /** 终端类型 */
  terminal: 'admin' | 'store' | 'miniapp' | 'shared';
  /** 输出格式 */
  format: 'css-variables' | 'ts-object' | 'scss-variables' | 'json';
  /** 输出路径（相对于项目根目录） */
  outputPath: string;
}

/**
 * 默认配置 — 根据实际 Figma 文件修改 fileKey
 */
export const defaultConfig: FigmaSyncConfig = {
  fileKey: process.env.FIGMA_FILE_KEY || '',
  accessToken: process.env.FIGMA_ACCESS_TOKEN || '',
  collections: ['Brand', 'Semantic', 'Neutral', 'Typography', 'Spacing', 'Elevation'],
  outputs: [
    // 共享 JSON（所有终端的唯一真相源）
    {
      terminal: 'shared',
      format: 'json',
      outputPath: 'shared/design-tokens/tokens.json',
    },
    // Admin 终端 — TypeScript 对象（Ant Design ConfigProvider 消费）
    {
      terminal: 'admin',
      format: 'ts-object',
      outputPath: 'apps/web-admin/src/theme/figma-tokens.ts',
    },
    // Store 终端 — CSS Variables（TXTouch 组件消费）
    {
      terminal: 'store',
      format: 'css-variables',
      outputPath: 'apps/web-pos/src/styles/figma-tokens.css',
    },
    // MiniApp 终端 — SCSS Variables（uni.scss 消费）
    {
      terminal: 'miniapp',
      format: 'scss-variables',
      outputPath: 'apps/miniapp-customer/src/figma-tokens.scss',
    },
  ],
};
