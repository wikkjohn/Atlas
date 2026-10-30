import { expect, test } from "@playwright/test";

import { DEMO_PASSWORD, nav, signIn, uniqueWord } from "./helpers";

test("System Settings: an administrator creates a user who then signs in with that role only", async ({ browser }) => {
  const username = `analyst.${uniqueWord()}`;
  const admin = await (await browser.newContext()).newPage();
  await signIn(admin, "admin", "/settings");

  await admin.getByRole("button", { name: "Create user" }).click();
  const form = admin.getByRole("form", { name: "Create a user" });
  await form.getByLabel("Username").fill(username);
  await form.getByLabel("Email").fill(`${username}@atlasbank.example`);
  await form.getByLabel("Display name").fill("New Auditor");
  await form.getByLabel("Initial password").fill(DEMO_PASSWORD);
  await form.getByLabel("Role").selectOption("auditor");
  await admin.getByRole("dialog").getByRole("button", { name: "Create user" }).click();
  // The dialog closes once the user exists; search only then.
  await expect(admin.getByRole("dialog")).toHaveCount(0);

  await admin.getByLabel("Search users").fill(username);
  const users = admin.getByRole("table", { name: "Users" });
  await expect(users.getByRole("row", { name: new RegExp(username) })).toBeVisible();
  await expect(users.getByLabel(`Role of ${username}`)).toHaveValue("auditor");

  // The new auditor signs in: read-only screens, no management actions.
  const auditor = await (await browser.newContext()).newPage();
  await signIn(auditor, username, "/");
  await expect(auditor.getByRole("heading", { name: "Enterprise Overview" })).toBeVisible();
  await expect(nav(auditor).getByRole("link", { name: "Audit Center" })).toBeVisible();
  await auditor.goto("/settings");
  await expect(auditor.getByRole("table", { name: "Role permissions" })).toBeVisible();
  await expect(auditor.getByRole("button", { name: "Create user" })).toHaveCount(0);

  // Deactivation takes effect on the next request.
  await users.getByRole("button", { name: `Deactivate ${username}` }).click();
  await expect(users.getByRole("row", { name: new RegExp(username) }).getByText("Inactive")).toBeVisible();
  await auditor.reload();
  await expect(auditor.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("System Settings: administrators see observability and simulation history", async ({ page }) => {
  await signIn(page, "admin", "/settings");
  const observability = page.getByRole("region", { name: "Observability" });
  await expect(observability.getByText("Jobs due")).toBeVisible();
  // This very page load went through the API, so the request table has rows.
  await expect(observability.getByRole("table", { name: "Request latency" }).getByText(/GET \/api\/v1\//).first()).toBeVisible();
  const history = page.getByRole("region", { name: "Simulation history" });
  await expect(history.getByRole("table", { name: "History partitions" }).getByText("Events")).toBeVisible();
});
