import { expect, test } from "@playwright/test";

import { nav, signIn } from "./helpers";

test.describe("Drill-down (Phase 88)", () => {
  test("opens from the navigation and drills one level down against the real backend", async ({ page }) => {
    await signIn(page, "researcher");
    await nav(page).getByRole("link", { name: "Drill-down" }).click();

    await expect(page.getByRole("heading", { name: "Drill-down" })).toBeVisible();
    const crumbs = page.getByRole("navigation", { name: "Drill-down path" });
    await expect(crumbs.getByText("ATLAS Global Bank")).toBeVisible();
    await expect(page.getByLabel("Summary")).toContainText("Executions");

    // The suite's own runs leave executions behind; when there are some, open the first group.
    const table = page.getByRole("table", { name: "Executions by country" });
    const empty = page.getByText("No executions here.");
    await expect(table.or(empty)).toBeVisible();
    if (await table.isVisible()) {
      const first = table.getByRole("link").first();
      const label = (await first.textContent())!.trim();
      await first.click();
      await expect(crumbs.getByText(label)).toHaveAttribute("aria-current", "page");
      await expect(page).toHaveURL(/[?&]country=/);
      await expect(page.getByRole("table", { name: "Executions by department" }).or(empty)).toBeVisible();
      await crumbs.getByRole("link", { name: "ATLAS Global Bank" }).click();
      await expect(table).toBeVisible();
    }

    await page.getByLabel("History").selectOption("live");
    await expect(page).toHaveURL(/realm=live/);
  });
});
