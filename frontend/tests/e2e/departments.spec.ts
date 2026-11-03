import { type Browser, expect, type Page, test } from "@playwright/test";

import { signIn } from "./helpers";

async function as(browser: Browser, username: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, username, "/departments");
  return page;
}

const row = (page: Page, text: string) => page.getByRole("table", { name: "Requests" }).getByRole("row").filter({ hasText: text });

test("Departments: a marketing campaign over the executive threshold needs an executive, then is completed", async ({ browser }) => {
  const clerk = await as(browser, "employee");
  await clerk.getByRole("list", { name: "Departments" }).getByRole("button", { name: /Marketing/ }).click();
  const form = clerk.getByRole("form", { name: "Submit request" });
  await form.getByLabel("Process").selectOption("campaign");
  await form.getByLabel("Title").fill(`Spring savings drive ${Date.now()}`);
  await form.getByLabel("Amount").fill("600000");
  await form.getByRole("button", { name: "Submit request" }).click();
  await expect(form.getByRole("status")).toContainText("submitted");
  const number = (await form.getByRole("status").innerText()).split(" ")[0];
  await expect(row(clerk, number)).toContainText("executive approval");
  // The requester cannot decide it.
  await expect(clerk.getByRole("button", { name: `Approve ${number}` })).toHaveCount(0);

  const manager = await as(browser, "manager");
  await manager.getByRole("list", { name: "Departments" }).getByRole("button", { name: /Marketing/ }).click();
  await manager.getByRole("button", { name: `Approve ${number}` }).click();
  await expect(manager.getByText(/executive approves/)).toBeVisible();

  const executive = await as(browser, "regional");
  await executive.getByRole("list", { name: "Departments" }).getByRole("button", { name: /Marketing/ }).click();
  await executive.getByRole("button", { name: `Approve ${number}` }).click();
  await expect(row(executive, number)).toContainText("approved");

  await clerk.reload();
  await clerk.getByRole("list", { name: "Departments" }).getByRole("button", { name: /Marketing/ }).click();
  await clerk.getByRole("button", { name: `Complete ${number}` }).click();
  await expect(row(clerk, number)).toContainText("completed");
});

test("Departments: a legal hold needs no approval and is completed by its requester", async ({ browser }) => {
  const clerk = await as(browser, "employee");
  const form = clerk.getByRole("form", { name: "Submit request" });
  await form.getByLabel("Process").selectOption("legal_hold");
  await expect(form.getByLabel("Amount")).toHaveCount(0);
  await form.getByLabel("Title").fill(`Preserve the lease emails ${Date.now()}`);
  await form.getByRole("button", { name: "Submit request" }).click();
  await expect(form.getByRole("status")).toContainText("approved");
  const number = (await form.getByRole("status").innerText()).split(" ")[0];
  await clerk.getByRole("button", { name: `Complete ${number}` }).click();
  await expect(row(clerk, number)).toContainText("completed");
});
