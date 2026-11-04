import os from 'node:os';
import path from 'node:path';

import { defineConfig } from '@playwright/test';

const port = Number(process.env.E2E_PORT ?? 8383);
process.env.E2E_PORT = String(port); // read by e2e/global-setup.ts
export const FAKE_PROWLARR_PORT = Number(process.env.E2E_PROWLARR_PORT ?? 8384);
process.env.E2E_PROWLARR_PORT = String(FAKE_PROWLARR_PORT);
// Deterministic so the server script and every test worker agree on it.
export const E2E_DIR = process.env.E2E_DIR ?? path.join(os.tmpdir(), 'magarr-e2e');
process.env.E2E_DIR = E2E_DIR;

export default defineConfig({
  testDir: 'e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://localhost:${port}`,
    // Local runs use the installed Chrome; CI installs Playwright's Chromium.
    channel: process.env.CI ? undefined : 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: './e2e/serve.sh',
      url: `http://localhost:${port}/health`,
      env: { E2E_DIR, E2E_PORT: String(port) },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `${process.env.MAGARR_PYTHON ?? '../backend/.venv/bin/python'} e2e/fake_prowlarr.py ${FAKE_PROWLARR_PORT}`,
      url: `http://127.0.0.1:${FAKE_PROWLARR_PORT}/ping`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
