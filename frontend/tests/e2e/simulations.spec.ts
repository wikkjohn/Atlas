import { expect, test } from "@playwright/test";

import { nav, signIn } from "./helpers";

test("Simulation Center: start a seeded run, review outcomes, reproduce it exactly", async ({ page }) => {
  test.setTimeout(180_000);
  const seed = String(1 + Math.floor(Math.random() * 1_000_000));

  await signIn(page, "researcher", "/");
  await nav(page).getByRole("link", { name: "Simulation Center" }).click();

  const form = page.getByRole("form", { name: "Start a simulation" });
  await expect(form.getByRole("option", { name: /Future enterprise scale/ })).toBeDisabled();
  await form.getByLabel("Workload").selectOption("custom");
  await form.getByLabel("Applications").fill("12");
  await form.getByLabel("Simulated staff").fill("5");
  await form.getByLabel("Random seed", { exact: true }).fill(seed);
  await form.getByRole("button", { name: "Start run" }).click();

  // The run executes in the background; the page polls until it finishes.
  const details = page.getByRole("region", { name: "Run details" });
  await expect(details.getByText("Completed", { exact: true })).toBeVisible({ timeout: 120_000 });
  const heading = await details.getByRole("heading", { name: /^Run #/ }).textContent();
  await expect(details.getByText("Cases completed")).toBeVisible();
  await expect(details.getByText("12 / 12")).toBeVisible();
  await expect(details.getByText(`seed ${seed}`, { exact: false })).toBeVisible();
  await expect(details.getByRole("table", { name: "Case results" }).getByRole("row")).toHaveCount(13);

  // Re-running with the same seed reproduces the same results, and says so.
  await details.getByRole("button", { name: "Run again with this seed" }).click();
  await expect(details.getByRole("heading", { name: /^Run #/ })).not.toHaveText(heading ?? "");
  await expect(details.getByText("Completed", { exact: true })).toBeVisible({ timeout: 120_000 });
  const original = heading?.replace("Run ", "") ?? "";
  await expect(details.getByText(`Run ${original}: identical results`)).toBeVisible();
});

test("Simulation Center: read-only roles see runs but cannot start them", async ({ page }) => {
  await signIn(page, "auditor", "/simulations");
  await expect(page.getByText("Your role can review runs but not start them.")).toBeVisible();
  await expect(page.getByRole("form", { name: "Start a simulation" })).toHaveCount(0);
});
