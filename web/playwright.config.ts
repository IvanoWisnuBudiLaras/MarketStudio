import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90000,
  use: {
    actionTimeout: 10000,
    viewport: { width: 1440, height: 1080 },
    launchOptions: { executablePath: process.env.MARKETSTUDIO_TEST_CHROMIUM },
  },
});
