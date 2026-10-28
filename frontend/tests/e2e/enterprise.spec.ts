import { expect, test } from "@playwright/test";

import { DEMO_PASSWORD, nav, signIn, uniqueWord } from "./helpers";

test("anonymous visitors must sign in and bad passwords are rejected", async ({ page }) => {
  await page.goto("/employees");
  await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();

  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(`${DEMO_PASSWORD}-wrong`);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid username or password.")).toBeVisible();

  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Returned to the page originally requested.
  await expect(page.getByRole("heading", { name: "Employees" })).toBeVisible();
});

test("administrator builds a team, hires into it, and the changes are audited", async ({
  page,
}) => {
  const suffix = uniqueWord();
  const teamName = `Onboarding Pod ${suffix}`;
  const lastName = `Testperson${suffix}`;
  await signIn(page, "admin", "/organization");

  // Navigate the hierarchy to a Japanese department and add a team.
  const tree = page.getByRole("list", { name: "Organization hierarchy" });
  await tree.getByRole("button", { name: "Expand Asia-Pacific Regional Headquarters" }).click();
  await tree.getByRole("button", { name: "Expand ATLAS Bank Japan" }).click();
  await tree.getByRole("button", { name: "Expand Retail Banking" }).click();
  await tree.getByRole("button", { name: /^Customer Onboarding/ }).click();
  await expect(page.getByRole("heading", { name: "Customer Onboarding" })).toBeVisible();
  await expect(page.getByText("JPY", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Add team" }).click();
  const addTeam = page.getByRole("dialog", { name: "Add team" });
  await addTeam.getByLabel("Name").fill(teamName);
  await addTeam.getByRole("button", { name: "Create" }).click();
  await expect(addTeam).toBeHidden();
  await tree.getByRole("button", { name: "Expand Customer Onboarding" }).first().click();
  await expect(tree.getByRole("button", { name: new RegExp(`^${teamName}`) })).toBeVisible();

  // Hire into the new team; compensation is entered in the country's currency.
  await nav(page).getByRole("link", { name: "Employees" }).click();
  await page.getByRole("button", { name: "Hire employee" }).click();
  const hire = page.getByRole("dialog", { name: "Hire employee" });
  await hire.getByLabel("First name").fill("Yuki");
  await hire.getByLabel("Last name").fill(lastName);
  await hire.getByLabel("Job title").fill("KYC Analyst");
  await hire.getByLabel("Unit").selectOption({ label: `JP · ${teamName} (team)` });
  await expect(hire.getByLabel("Annual compensation (JPY)")).toBeEnabled();
  await hire.getByLabel("Annual compensation (JPY)").fill("7200000");
  await hire.getByRole("button", { name: "Hire" }).click();
  await expect(hire).toBeHidden();

  await page.getByRole("textbox", { name: "Search employees" }).fill(lastName);
  await page.getByRole("textbox", { name: "Search employees" }).press("Enter");
  const row = page.getByRole("row", { name: new RegExp(lastName) });
  await expect(row).toContainText(teamName);
  await expect(row).toContainText("¥7,200,000");

  // The audit log shows who did it.
  await nav(page).getByRole("link", { name: "Audit Center" }).click();
  await page.getByRole("textbox", { name: "Action" }).fill("employee.created");
  const event = page.getByRole("row").filter({ hasText: "employee.created" }).first();
  await expect(event).toContainText("admin");
  await event.click();
  await expect(page.getByLabel("Event metadata")).toContainText('"annual_compensation": "[redacted]"');
});

test("a banking employee cannot see compensation or the audit log", async ({ page }) => {
  await signIn(page, "employee", "/employees");

  await expect(page.getByRole("row").nth(1)).toContainText("Restricted");
  await expect(page.getByRole("button", { name: "Hire employee" })).toHaveCount(0);
  await expect(nav(page).getByText("Audit Center")).toHaveCount(0);

  // Even going to the URL directly, the backend refuses.
  await page.goto("/audit");
  await expect(page.getByRole("alert")).toContainText("Access denied");
});
