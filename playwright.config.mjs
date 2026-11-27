import { defineConfig } from '@playwright/test';

const baseURL = process.env.PILOT_REVIEW_URL || 'http://127.0.0.1:8765';
const origin = new URL(baseURL);
if (origin.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(origin.hostname)
    || origin.pathname !== '/' || origin.username || origin.password || origin.search) {
  throw new Error('Browser checks require an isolated localhost review origin.');
}

export default defineConfig({
  testDir: './tests/browser',
  timeout: 90_000,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: 'phase6-artifacts/browser-results.json' }]],
  use: { baseURL, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { browserName: 'chromium', viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { browserName: 'chromium', viewport: { width: 390, height: 844 } } },
  ],
});
