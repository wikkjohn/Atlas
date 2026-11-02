import { type Browser, expect, type Page, test } from "@playwright/test";

import { DEMO_PASSWORD, signIn } from "./helpers";

const API_URL = process.env.ATLAS_E2E_API_URL ?? "http://localhost:8000";

async function as(browser: Browser, username: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, username, "/hr");
  return page;
}

test("Human Resources: a manager opens a requisition, an executive approves it, and the manager hires the candidate", async ({ browser }) => {
  const manager = await as(browser, "manager");
  const form = manager.getByRole("form", { name: "Open requisition" });
  const department = form.getByLabel("Department");
  await expect(department.locator("option")).not.toHaveCount(1);
  await department.selectOption({ index: 1 });
  await form.getByLabel("Job title").fill("Onboarding Adviser");
  await form.getByLabel("Salary from").fill("40000");
  await form.getByLabel("Salary to").fill("50000");
  await form.getByLabel("Reason").fill("Two advisers left this month");
  await form.getByRole("button", { name: "Open requisition" }).click();
  const status = form.getByRole("status");
  await expect(status).toContainText("opened");
  const number = (await status.innerText()).split(" ")[0];
  // The requester cannot approve the headcount: executives do (hr:approve).
  await expect(manager.getByRole("button", { name: `Approve ${number}` })).toHaveCount(0);

  const regional = await as(browser, "regional");
  await regional.getByRole("button", { name: `Approve ${number}` }).click();
  const approved = regional.getByRole("table", { name: "Requisitions" }).getByRole("row").filter({ hasText: number });
  await expect(approved).toContainText("approved");

  await manager.reload();
  await manager.getByLabel(`Candidate name for ${number}`).fill("Rina Okafor");
  await manager.getByRole("button", { name: `Add candidate to ${number}` }).click();
  const row = manager.getByRole("table", { name: "Requisitions" }).getByRole("row").filter({ hasText: number });
  await expect(row).toContainText("Rina Okafor");
  const candidate = (await row.getByText(/^CAN-\d+$/).first().innerText()).trim();
  // An offer outside the band is refused.
  await manager.getByLabel(`Offer salary for ${candidate}`).fill("90000");
  await manager.getByRole("button", { name: `Offer ${candidate}` }).click();
  await expect(manager.getByText(/within the band/)).toBeVisible();
  await manager.getByLabel(`Offer salary for ${candidate}`).fill("45000");
  await manager.getByRole("button", { name: `Offer ${candidate}` }).click();
  await manager.getByRole("button", { name: `Hire ${candidate}` }).click();
  await expect(row).toContainText("hired");
  await expect(row.getByText(/^AGB-\d+$/)).toBeVisible();
  await expect(manager.getByRole("table", { name: "Onboarding tasks" })).toContainText("Signed contract on file");
});

test("Human Resources: leave is counted in business days and decided by someone else", async ({ browser, request }) => {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, { data: { username: "manager", password: DEMO_PASSWORD } });
  const { access_token: token } = (await login.json()) as { access_token: string };
  const employees = await request.get(`${API_URL}/api/v1/employees?limit=1`, { headers: { Authorization: `Bearer ${token}` } });
  const { items } = (await employees.json()) as { items: { employee_number: string }[] };
  const employee = items[0].employee_number;

  const manager = await as(browser, "manager");
  const form = manager.getByRole("form", { name: "Request leave" });
  await form.getByLabel("Employee number").fill(employee);
  await form.getByLabel("From").fill("2041-03-05");
  await form.getByLabel("To").fill("2041-03-07");
  await form.getByRole("button", { name: "Request leave" }).click();
  const status = form.getByRole("status");
  await expect(status).toContainText("3 days");
  const leave = (await status.innerText()).split(":")[0];
  // The requester cannot approve it.
  await manager.getByRole("button", { name: `Approve ${leave}` }).click();
  await expect(manager.getByText(/Four-eyes rule/)).toBeVisible();

  const admin = await as(browser, "admin");
  await admin.getByRole("button", { name: `Approve ${leave}` }).click();
  await expect(admin.getByRole("table", { name: "Leave requests" }).getByRole("row").filter({ hasText: leave })).toContainText("approved");
});
