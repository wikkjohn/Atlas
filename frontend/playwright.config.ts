import { defineConfig, devices } from "@playwright/test";

// End-to-end tests drive the real frontend against the real backend and database.
// Both servers are started automatically unless they are already running.
const backendCommand =
  process.env.ATLAS_E2E_BACKEND_COMMAND ??
  "cd ../backend && .venv/bin/uvicorn app.main:app --port 8000";

export default defineConfig({
  testDir: "./tests/e2e",
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
