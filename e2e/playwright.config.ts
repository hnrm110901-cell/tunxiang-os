import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  retries: 1,
  fullyParallel: true,
  reporter: [['html', { open: 'never' }], ['list']],

  use: {
    baseURL: 'http://localhost:5173',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    actionTimeout: 10_000,
  },

  projects: [
    {
      name: 'web-admin',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /\/(auth|dish-management|member|navigation)\./,
    },
    {
      name: 'web-pos',
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:5174',
      },
      testMatch: /\/cashier\./,
    },
    {
      // Sprint A2 / PR E：断网收银 4 场景
      // 独立 project 以便 CI 单独跑（`--project=offline`）和 nightly 时注入 OFFLINE_HOURS
      name: 'offline',
      timeout: 90_000,
      use: {
        ...devices['Desktop Chrome'],
        baseURL: process.env.POS_BASE_URL ?? 'http://localhost:5174',
      },
      testMatch: /\/offline-cashier\./,
    },
  ],
});
