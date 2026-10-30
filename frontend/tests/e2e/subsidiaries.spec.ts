import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

// Kenya sorts after the operating countries, so simulations keep hiring where they did.
test("Organization: an administrator launches Kenya and its subsidiary is generated", async ({ page }) => {
  await signIn(page, "admin", "/organization");
  const panel = page.getByRole("region", { name: "Country subsidiaries" });
  await expect(panel.getByText(/Blueprint v1: 12 units and 24 synthetic staff/)).toBeVisible();
  await expect(panel.getByRole("table", { name: "Subsidiary coverage" }).getByText("Middle East & Africa")).toBeVisible();

  const form = panel.getByRole("form", { name: "Generate subsidiaries" });
  await form.getByLabel("Country codes").fill("KE");
  await form.getByRole("button", { name: "Generate" }).click();
  await expect(panel.getByRole("status")).toContainText("Launched 1 of 1 countries");

  const tree = page.getByRole("list", { name: "Organization hierarchy" });
  await tree.getByRole("button", { name: "Expand Middle East & Africa Regional Headquarters" }).click();
  await tree.getByRole("button", { name: /^ATLAS Bank Kenya/ }).click();
  const details = page.getByRole("region", { name: "Details" });
  await expect(details.getByRole("heading", { name: "ATLAS Bank Kenya" })).toBeVisible();
  await expect(details.getByText("Generated (subsidiary-blueprint/1)")).toBeVisible();
  await expect(details.getByText("KES")).toBeVisible();
});
