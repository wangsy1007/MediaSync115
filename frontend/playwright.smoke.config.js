import { defineConfig, devices } from '@playwright/test'

const frontendBaseUrl = process.env.PLAYWRIGHT_FRONTEND_BASE_URL || 'http://127.0.0.1:5173'
const backendHealthUrl = process.env.PLAYWRIGHT_BACKEND_HEALTH_URL || 'http://127.0.0.1:8000/health'
const authStorageState = './test-results/.auth/smoke-user.json'

export default defineConfig({
  testDir: './tests/smoke',
  timeout: 90_000,
  expect: {
    timeout: 20_000
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: frontendBaseUrl,
    storageState: authStorageState,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure'
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome']
      }
    }
  ],
  globalSetup: './tests/smoke/global-setup.js',
  metadata: {
    frontendBaseUrl,
    backendHealthUrl
  }
})
