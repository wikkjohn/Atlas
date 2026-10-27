import { execSync } from "node:child_process";

/** Ensure the demo bank and demo users exist. The seed is idempotent. */
export default function globalSetup(): void {
  const command =
    process.env.ATLAS_E2E_SEED_COMMAND ?? "cd ../backend && .venv/bin/python -m app.cli seed-demo";
  execSync(command, { stdio: "inherit" });
}
