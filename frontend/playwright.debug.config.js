import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import { resolve, dirname } from 'node:path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const frontendBaseUrl = 'http://127.0.0.1:5173'
const authStorageState = resolve(__dirname, '.auth/smoke-user.json')

export default defineConfig({
  testDir: './tests/smoke',
  testMatch: '**/debug.spec.js',
  timeout: 60_000,
  expect: {
    timeout: 20_000
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: frontendBaseUrl,
    storageState: authStorageState,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
      }
    }
  ],
})
