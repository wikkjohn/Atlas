import { expect, test } from "@playwright/test";

test.describe("Phase 1 platform shell", () => {
  test("overview displays live health from the real backend and database", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Platform Overview" })).toBeVisible();
    const database = page.getByRole("group", { name: "Database" });
    await expect(database.getByText("Connected")).toBeVisible();
    await expect(database.getByText(/PostgreSQL · [\d.]+ ms round trip/)).toBeVisible();

    const migrations = page.getByRole("group", { name: "Schema migrations" });
    await expect(migrations.getByText("Up to date")).toBeVisible();
    await expect(migrations.getByText(/0001_platform_baseline/)).toBeVisible();

    const roadmap = page.getByRole("region", { name: "Module roadmap" });
    await expect(roadmap.getByRole("cell", { name: "Platform core" })).toBeVisible();
    await expect(roadmap.getByRole("cell", { name: "Workflow engine" })).toBeVisible();

    await expect(page.getByText("Synthetic data", { exact: true })).toBeVisible();
  });

  test("shows a failure state when the backend is unreachable and recovers", async ({ page }) => {
    // Simulate the API being down at the network layer.
    await page.route("**/api/**", (route) => route.abort("connectionrefused"));
    await page.goto("/");

    const alert = page.getByRole("alert");
    await expect(alert.getByText("The ATLAS API is unavailable")).toBeVisible();
    await expect(page.getByTestId("connection-indicator")).toHaveText("API unreachable");

    await page.unroute("**/api/**");
    await alert.getByRole("button", { name: /retry connection/i }).click();

    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(
      page.getByRole("group", { name: "Database" }).getByText("Connected"),
    ).toBeVisible();
  });

  test("navigation works on a phone-sized screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/missing-page");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();

    await page.getByRole("button", { name: "Open navigation" }).click();
    const nav = page.getByRole("navigation", { name: "Primary" });
    await expect(nav.getByText("AI Innovation Lab")).toBeVisible();
    await nav.getByRole("link", { name: "Overview" }).click();

    await expect(page.getByRole("heading", { name: "Platform Overview" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeHidden();
  });
});
