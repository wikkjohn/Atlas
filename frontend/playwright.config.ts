import { defineConfig, devices } from "@playwright/test";

// End-to-end tests drive the real frontend against the real backend and database.
// Both servers are started automatically unless they are already running.
const backendCommand =
  process.env.ATLAS_E2E_BACKEND_COMMAND ??
  // The suite signs the same demo users in many times from one address: raise the
  // sign-in rate limits (Phase 85), which stay on for everything else.
  `cd ../backend && ATLAS_RATE_LIMIT_OVERRIDES='{"login.user":100000,"login.ip":100000}' .venv/bin/uvicorn app.main:app --port 8000`;

export default defineConfig({
  testDir: "./tests/e2e",
  globalSetup: "./tests/e2e/global-setup.ts",
  fullyParallel: true,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: backendCommand,
      url: "http://localhost:8000/api/health",
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: "npm run dev -- --strictPort",
      url: "http://localhost:5173",
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
