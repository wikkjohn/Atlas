import { type Browser, expect, type Page, test } from "@playwright/test";

import { signIn, uniqueWord } from "./helpers";

async function as(browser: Browser, username: string, path: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, username, path);
  return page;
}

test("WF-0001: missing documents → wait → resume → four-eyes approval → account opened", async ({ browser }) => {
  const name = `Grace ${uniqueWord().replace(/^./, (c) => c.toUpperCase())}`;

  // A teller starts an application without proof of address.
  const teller = await as(browser, "employee", "/workflows");
  await teller.getByRole("button", { name: "Start an application" }).click();
  const form = teller.getByRole("dialog");
  await form.getByLabel("Applicant name").fill(name);
  await form.getByLabel("Date of birth").fill("1986-12-09");
  await form.getByLabel("Country").selectOption("US");
  await form.getByLabel("Proof of address (synthetic)").uncheck();
  await form.getByRole("button", { name: "Submit application" }).click();

  // The case waits for documents; submitting them resumes it up to the approval gate.
  const caseView = teller.getByRole("dialog", { name: "Workflow execution" });
  await expect(caseView.getByText("This case is waiting for documents.")).toBeVisible();
  await caseView.getByRole("button", { name: "Submit synthetic documents" }).click();
  const approvalRow = caseView.getByRole("row", { name: /Authorized approval/ });
  await expect(approvalRow.getByText("waiting")).toBeVisible();
  await expect(caseView.getByRole("row", { name: /Create the customer account/ })).toHaveCount(0);
  await teller.keyboard.press("Escape");

  // The teller cannot decide their own case.
  await teller.getByRole("tab", { name: "Task inbox" }).click();
  await teller.getByLabel("Only tasks I can act on").uncheck();
  const ownTask = teller.getByRole("listitem").filter({ hasText: name });
  await expect(ownTask.getByRole("button", { name: /Approve/ })).toHaveCount(0);

  // A manager approves; the workflow opens the account and closes the case.
  const manager = await as(browser, "manager", "/workflows?tab=tasks");
  const task = manager.getByRole("listitem").filter({ hasText: name });
  await task.getByLabel(`Note for ${name}`).fill("Documents verified");
  await task.getByRole("button", { name: /Approve/ }).click();
  await expect(task).toHaveCount(0);

  await manager.getByRole("tab", { name: "Executions" }).click();
  await manager.getByRole("row").filter({ hasText: name }).first().click();
  const done = manager.getByRole("dialog", { name: "Workflow execution" });
  await expect(done.getByText("Completed", { exact: true })).toBeVisible();
  await expect(done.getByText("Approved", { exact: true })).toBeVisible();
  await expect(done.getByRole("row", { name: /Create the customer account/ }).getByText("completed")).toBeVisible();
  await expect(done.getByRole("row", { name: /Authorized approval/ })).toContainText("manager");

  // The customer now exists, verified, with an open account.
  await manager.goto(`/customers?q=${encodeURIComponent(name)}`);
  const customerRow = manager.getByRole("row", { name: new RegExp(name) });
  await expect(customerRow.getByText("KYC verified")).toBeVisible();
  await customerRow.click();
  await expect(manager.getByRole("region", { name: "Accounts" }).getByText("Open")).toBeVisible();
});
