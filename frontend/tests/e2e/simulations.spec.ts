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

test("Experiments: baseline vs. AI on one workload → evaluation → report → benchmarking", async ({ page }) => {
  test.setTimeout(240_000);
  await signIn(page, "researcher", "/");
  await nav(page).getByRole("link", { name: "Experiments" }).click();
  await page.getByRole("button", { name: "New experiment" }).click();

  const form = page.getByRole("form", { name: "New experiment" });
  const name = `E2E automated ${Date.now()}`;
  await form.getByLabel("Name").fill(name);
  await form.getByLabel("Candidate configuration").selectOption("ai_automated");
  await form.getByLabel("Applications").fill("15");
  await form.getByLabel("Staff").fill("5");
  await form.getByLabel("Seed").fill(String(1 + Math.floor(Math.random() * 1_000_000)));
  await form.getByLabel("Reviewer cost per minute").fill("0.9");
  await page.getByRole("button", { name: "Run experiment" }).click();

  // Both runs execute in the background; the evaluation appears when they finish.
  const details = page.getByRole("region", { name: "Experiment details" });
  await expect(details.getByRole("heading", { name: new RegExp(name) })).toBeVisible();
  await expect(details.getByRole("list", { name: "Success criteria" })).toBeVisible({ timeout: 180_000 });
  await expect(details.getByRole("table", { name: "Metric comparison" })).toBeVisible();
  await expect(details.getByText("reviewer cost per minute", { exact: false }).first()).toBeAttached();

  // The proof-of-concept report downloads with the assumptions and limitations.
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    details.getByRole("button", { name: "Report (.md)" }).click(),
  ]);
  const path = await download.path();
  const { readFile } = await import("node:fs/promises");
  const report = await readFile(path!, "utf8");
  expect(report).toContain("# Proof-of-concept report");
  expect(report).toContain("| reviewer cost per minute | 0.9 |");
  expect(report).toContain("## Known limitations");

  // Re-evaluating from the stored raw measurements reproduces the result.
  await details.getByRole("button", { name: "Re-evaluate" }).click();
  await expect(details.getByRole("status")).toContainText("identical result");

  // Benchmarking charts the same experiment.
  await details.getByRole("link", { name: "Benchmarking" }).click();
  await expect(page.getByRole("table", { name: "Tool benchmarks" })).toContainText("agb-intelligent-kyc-assistant");
  await expect(page.getByRole("figure", { name: /Processing time per case/ })).toBeVisible();
  await expect(page.getByRole("figure", { name: /Estimated operating cost/ })).toBeVisible();
});

test("DEMO (Part 12): AI-assisted bank account opening, end to end", async ({ page }) => {
  test.setTimeout(300_000);
  const seed = String(1 + Math.floor(Math.random() * 1_000_000));

  // Step 1 — An authorized AI researcher signs in.
  await signIn(page, "researcher", "/");

  // Step 2 — Explore the enterprise: dashboard, organization, employees.
  await expect(page.getByRole("heading", { name: "Enterprise Overview" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Key metrics" }).getByRole("link", { name: /^Employees: / })).toBeVisible();
  await nav(page).getByRole("link", { name: "Organization" }).click();
  await expect(page.getByRole("heading", { name: "Organization", level: 1 })).toBeVisible();
  await nav(page).getByRole("link", { name: "Employees" }).click();
  await expect(page.getByRole("heading", { name: "Employees", level: 1 })).toBeVisible();

  // Step 3 — Open WF-0001 Retail Account Opening.
  await nav(page).getByRole("link", { name: "Workflow Explorer" }).click();
  await expect(page.getByRole("heading", { name: "Retail Account Opening" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Process steps" }).getByText("AI KYC assistant review (advisory)")).toBeVisible();

  // Steps 4–7 — 100 seeded applications; baseline and AI-assisted runs on the same applications,
  // with the AGB Intelligent KYC Assistant and human approval preserved.
  await nav(page).getByRole("link", { name: "Experiments" }).click();
  await page.getByRole("button", { name: "New experiment" }).click();
  const form = page.getByRole("form", { name: "New experiment" });
  await form.getByLabel("Name").fill(`Demo ${seed}: KYC assistant, AI assisted`);
  await form.getByLabel("AI tool").selectOption("agb-intelligent-kyc-assistant");
  await form.getByLabel("Candidate configuration").selectOption("ai_assisted");
  await form.getByLabel("Applications").fill("100");
  await form.getByLabel("Staff").fill("25");
  await form.getByLabel("Seed").fill(seed);
  await page.getByRole("button", { name: "Run experiment" }).click();

  // Step 8 — The evaluation engine compares timing, cost, accuracy and review effort.
  const details = page.getByRole("region", { name: "Experiment details" });
  await expect(details.getByRole("heading", { name: new RegExp(`Demo ${seed}:`) })).toBeVisible();
  await expect(details.getByRole("list", { name: "Success criteria" })).toBeVisible({ timeout: 240_000 });
  const comparison = details.getByRole("table", { name: "Metric comparison" });
  for (const metric of ["Workflow processing time (average cycle)", "Simulated labour time", "Cost per completed case", "Decisions matching ground truth", "Manual reviews"]) {
    await expect(comparison.getByRole("row", { name: new RegExp(metric.replace(/[()]/g, ".")) })).toBeVisible();
  }
  // Human approval was preserved: the AI-assisted run still has every manual review.
  const reviews = comparison.getByRole("row", { name: /^Manual reviews/ });
  const cells = await reviews.getByRole("cell").allTextContents();
  expect(cells[1]).toBe(cells[2]);

  // Step 9 — Review failures: misclassifications, escalations, exceptions, policy violations.
  await expect(details.getByText(/account decisions checked: 0 violation/)).toBeVisible();
  await details.getByRole("link", { name: /B — AI assisted — run #/ }).click();
  const run = page.getByRole("region", { name: "Run details" });
  await expect(run.getByRole("region", { name: "AI tool behaviour" })).toContainText("Recommendations:");
  await run.getByLabel("Only cases whose outcome differs from the ground truth").check();
  await expect(run.getByRole("table", { name: "Case results" })).toBeVisible();
  await page.goBack();

  // Step 10 — Export the proof-of-concept report.
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("region", { name: "Experiment details" }).getByRole("button", { name: "Report (.md)" }).click(),
  ]);
  const { readFile } = await import("node:fs/promises");
  const report = await readFile((await download.path())!, "utf8");
  for (const section of [
    "## Tested tool",
    "## Test scenario and workload",
    `Data seed: \`${seed}\``,
    "Software version",
    "## Baseline and AI performance",
    "## Operational differences",
    "## Financial assumptions",
    "## Security and compliance results",
    "## Known limitations",
    "## Recommendation",
  ]) {
    expect(report).toContain(section);
  }
});
