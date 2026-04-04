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
  ],
});
