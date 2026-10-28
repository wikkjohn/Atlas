import { expect, test } from "@playwright/test";

import { nav, signIn } from "./helpers";

// Only one simulation runs at a time, so the tests that start runs go one after another.
test.describe.configure({ mode: "serial" });

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

test("AI Innovation Lab: try the KYC assistant, see a blocked action, run A/B/C on one seed", async ({ page }) => {
  test.setTimeout(240_000);
  await signIn(page, "researcher", "/");
  await nav(page).getByRole("link", { name: "AI Innovation Lab" }).click();

  const registry = page.getByRole("list", { name: "AI tools" });
  await registry.getByRole("button", { name: /AGB Intelligent KYC Assistant/ }).click();
  const details = page.getByRole("region", { name: "Tool details" });
  await expect(details.getByRole("heading", { name: "AGB Intelligent KYC Assistant" })).toBeVisible();

  // The test console calls the real tool; the call is recorded.
  const console = details.getByRole("form", { name: "Test console" });
  await console.getByLabel("Action").selectOption("recommend_decision");
  await console.getByRole("button", { name: "Invoke" }).click();
  await expect(console.getByRole("status")).toContainText("Recommendation: Approve");

  // The fault injector was not granted complete_low_risk_review: the call is blocked.
  await registry.getByRole("button", { name: /KYC Fault Injector/ }).click();
  const faulty = details.getByRole("form", { name: "Test console" });
  await faulty.getByLabel("Action").selectOption("complete_low_risk_review");
  await faulty.getByRole("button", { name: "Invoke" }).click();
  await expect(faulty.getByText(/not permitted to perform/)).toBeVisible();

  // Experiment: the three configurations on the same seeded applications.
  await registry.getByRole("button", { name: /AGB Intelligent KYC Assistant/ }).click();
  const experiment = details.getByRole("form", { name: "Configure an experiment" });
  await experiment.getByLabel("Applications").fill("15");
  await experiment.getByLabel("Staff").fill("5");
  await experiment.getByLabel("Seed").fill(String(1 + Math.floor(Math.random() * 1_000_000)));
  await experiment.getByRole("button", { name: "Start test runs" }).click();

  const runs = details.getByRole("table", { name: "Experiment runs" });
  for (const label of ["A — Baseline", "B — AI assisted", "C — AI automated tasks"]) {
    await expect(runs.getByRole("row", { name: new RegExp(label) }).getByText("Completed")).toBeVisible({
      timeout: 180_000,
    });
  }
  // Each run opens in the Simulation Center with its full results.
  await runs.getByRole("link", { name: "C — AI automated tasks" }).click();
  await expect(page.getByRole("region", { name: "AI tool behaviour" })).toBeVisible();
});
