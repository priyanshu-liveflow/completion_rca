import { defineConfig, devices } from "@playwright/test";
import { mkdirSync, mkdtempSync } from "node:fs";
import path from "node:path";

// Each run owns its store/export. Never overwrite a developer's review history.
const root = path.resolve(__dirname, "../..");
mkdirSync(path.join(root, ".e2e"), { recursive: true });
const stateDir = mkdtempSync(path.join(root, ".e2e/run-"));

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{
    name: "chromium",
    use: {
      ...devices["Desktop Chrome"],
      viewport: { width: 1920, height: 1000 },
    },
  }],
  webServer: {
    command: "npm run start -- --hostname 127.0.0.1 --port 3100",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      AGENTRADAR_STORE_PATH: path.join(stateDir, "agentradar.db"),
      AGENTRADAR_REVIEW_EXPORT: path.join(stateDir, "review-runs.json"),
    },
  },
});
