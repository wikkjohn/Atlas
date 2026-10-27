import { expect, test } from "@playwright/test";

import { nav, signIn } from "./helpers";

test.describe("Platform shell", () => {
  test("overview displays live health from the real backend and database", async ({ page }) => {
    await signIn(page, "researcher");

    await expect(page.getByRole("heading", { name: "Platform Overview" })).toBeVisible();
    const database = page.getByRole("group", { name: "Database" });
    await expect(database.getByText("Connected")).toBeVisible();
    await expect(database.getByText(/PostgreSQL · [\d.]+ ms round trip/)).toBeVisible();

    const migrations = page.getByRole("group", { name: "Schema migrations" });
    await expect(migrations.getByText("Up to date")).toBeVisible();
    await expect(migrations.getByText(/head \d{4}_\w+/)).toBeVisible();

    const roadmap = page.getByRole("region", { name: "Module roadmap" });
    await expect(roadmap.getByRole("cell", { name: "Platform core" })).toBeVisible();
    await expect(page.getByText("Synthetic data", { exact: true })).toBeVisible();
  });

  test("shows a failure state when the backend becomes unreachable and recovers", async ({
    page,
  }) => {
    await signIn(page, "researcher");
    await expect(page.getByText("All systems operational")).toBeVisible();

    await page.route("**/api/**", (route) => route.abort("connectionrefused"));
    await page.getByRole("button", { name: "Refresh" }).click();

    const alert = page.getByRole("alert");
    await expect(alert.getByText("The ATLAS API is unavailable")).toBeVisible();
    await expect(page.getByTestId("connection-indicator")).toHaveText("API unreachable");

    await page.unroute("**/api/**");
    await alert.getByRole("button", { name: /retry connection/i }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Database" }).getByText("Connected")).toBeVisible();
  });

  test("navigation works on a phone-sized screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page, "researcher", "/missing-page");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();

    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(nav(page).getByText("AI Innovation Lab")).toBeVisible();
    await nav(page).getByRole("link", { name: "Overview" }).click();

    await expect(page.getByRole("heading", { name: "Platform Overview" })).toBeVisible();
    await expect(nav(page)).toBeHidden();
  });
});
