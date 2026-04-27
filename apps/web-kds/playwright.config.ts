/**
 * Sprint C / C4 — web-kds 4 小时零卡顿 E2E 配置
 *
 * 目的：作为周 8 验收"断网恢复 4 小时无数据丢失"门禁的关键证据。
 *
 * 模式（由 KDS_E2E_DURATION_MS 环境变量切换）：
 *   - fast (默认 60_000ms = 60s)：PR 门禁、本地快速验证
 *   - nightly (14_400_000ms = 4h)：CI 凌晨跑，nightly artifacts
 *
 * Tier 1：测试用例必须基于真实餐厅场景（CLAUDE.md §20）。
 *   见 e2e/kds-4h-zero-jank.spec.ts。
 *
 * 测试页来源：
 *   1. 默认（KDS_BASE_URL 未设）：spec 内部启动 mockDeltaServer，它同时充当
 *      静态宿主 + delta API。这是为了规避 worktree 中 vite dev server
 *      因 packages/* 不在 pnpm-workspace 而 import-analysis 失败的问题。
 *   2. 设 KDS_BASE_URL=http://localhost:5173：用真实 vite dev server 跑同样
 *      用例（一旦上游 vite 修好即切换）。
 *
 * 注意：
 *   - retries 0：长跑测试一旦失败，需要看完整 trace；自动重试只会浪费时间
 *   - workers 1：4h 测试不能并行（会抢 CPU 让 jank 数据失真）
 *   - timeout 包含 buffer，nightly 模式 4.5h
 */
import { defineConfig, devices } from '@playwright/test';

const DURATION_MS = Number(process.env.KDS_E2E_DURATION_MS ?? 60_000);
const IS_NIGHTLY = DURATION_MS >= 60 * 60 * 1000; // ≥1h 视为 nightly

// 测试用例本身的超时 = 跑测时长 + 60s buffer（启动/截图/收集指标）
const TEST_TIMEOUT_MS = DURATION_MS + 60_000;

// 真 vite dev server 模式：设 KDS_BASE_URL=http://localhost:5173 自动起服
// （上游 packages/* 已加入 pnpm-workspace，vite import-analysis 不再失败）
const KDS_BASE_URL = process.env.KDS_BASE_URL;
const USE_REAL_VITE = !!KDS_BASE_URL;

export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.spec\.ts$/,
  timeout: TEST_TIMEOUT_MS,
  // 全局超时：单个 spec 最长执行时间（含 fixture 启动）
  globalTimeout: TEST_TIMEOUT_MS + 120_000,
  retries: 0,
  workers: 1,
  fullyParallel: false,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],

  use: {
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
    screenshot: 'only-on-failure',
    trace: IS_NIGHTLY ? 'off' : 'retain-on-failure', // 4h trace 文件太大，nightly 关掉
    video: 'off',
    ...(USE_REAL_VITE ? { baseURL: KDS_BASE_URL } : {}),
  },

  // 真 vite 模式下自动起 dev server；mock 模式下不需要任何外部服务
  ...(USE_REAL_VITE
    ? {
        webServer: {
          // 在 worktree 根跑，避免 monorepo workspace 解析问题
          command: 'pnpm --filter web-kds dev',
          cwd: '../..',
          url: KDS_BASE_URL,
          reuseExistingServer: !process.env.CI,
          timeout: 60_000,
          stdout: 'pipe',
          stderr: 'pipe',
        },
      }
    : {}),

  projects: [
    {
      name: 'kds-zero-jank',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
