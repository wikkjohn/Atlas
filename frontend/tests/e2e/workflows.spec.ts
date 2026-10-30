import { type Browser, expect, type Page, test } from "@playwright/test";

import { fundedAccount, signIn, uniqueWord } from "./helpers";

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

test("WF-1001 (stored definition): generated start form → colleague approval → letter; next version validates", async ({ browser, request }) => {
  const { customerNumber: customer } = await fundedAccount(request, 0);

  // A teller starts the imported workflow from the form generated from its input schema.
  const teller = await as(browser, "employee", "/workflows");
  await teller.getByRole("list", { name: "Workflows" }).getByText("Customer Address Change").click();
  await expect(teller.getByText("Stored definition (imported as data)")).toBeVisible();
  await teller.getByRole("button", { name: "Start a case" }).click();
  const form = teller.getByRole("dialog", { name: /Start Customer Address Change/ });
  await form.getByLabel("Customer number").fill(customer);
  await form.getByLabel("Street").fill("12 Synthetic Lane");
  await form.getByLabel("City").fill("Leeds");
  await form.getByLabel("Postal code").fill("LS1 4AP");
  await form.getByLabel("Country code").fill("GB");
  await form.getByLabel("Reason").selectOption("moved");
  await form.getByRole("button", { name: "Start case" }).click();
  const caseView = teller.getByRole("dialog", { name: "Workflow execution" });
  await expect(caseView.getByRole("row", { name: /Colleague checks the new address/ }).getByText("waiting")).toBeVisible();
  await expect(caseView.getByRole("row", { name: /Find the customer/ }).getByText("completed")).toBeVisible();

  // A colleague (four-eyes) approves from the task inbox; the case completes with a letter.
  const manager = await as(browser, "manager", "/workflows?tab=tasks");
  const task = manager.getByRole("listitem").filter({ hasText: customer });
  await task.getByRole("button", { name: /Approve/ }).click();
  await expect(task).toHaveCount(0);
  await manager.getByRole("tab", { name: "Executions" }).click();
  await manager.getByRole("row").filter({ hasText: customer }).first().click();
  const done = manager.getByRole("dialog", { name: "Workflow execution" });
  await expect(done.getByText("Completed", { exact: true })).toBeVisible();
  await expect(done.getByText("Updated", { exact: true })).toBeVisible();
  await expect(done.getByRole("row", { name: /Confirm to the customer/ }).getByText("completed")).toBeVisible();

  // An administrator drafts the next version from the stored one and validates it.
  const admin = await as(browser, "admin", "/workflows");
  await admin.getByRole("list", { name: "Workflows" }).getByText("Customer Address Change").click();
  await admin.getByRole("button", { name: "Import definition" }).click();
  const importer = admin.getByRole("dialog", { name: "Import a workflow definition" });
  await importer.getByRole("button", { name: /Start from WF-1001/ }).click();
  await expect(importer.getByLabel("Definition (JSON)")).toHaveValue(/"workflow_id": "WF-1001"/);
  await importer.getByRole("button", { name: "Validate" }).click();
  await expect(importer.getByText(/is valid and can be imported/)).toBeVisible();
  await expect(importer.getByRole("list", { name: "Effects" })).toContainText("notify_updated");
});

test("WF-1002 (stored definition): a paper-statement fee is charged only after a colleague approves", async ({ browser, request }) => {
  const { accountNumber, customerNumber, customerName } = await fundedAccount(request, 1_000);

  const teller = await as(browser, "employee", "/workflows");
  await teller.getByRole("list", { name: "Workflows" }).getByText("Paper Statement Request").click();
  await expect(teller.getByRole("row", { name: /Charge the paper-statement fee/ }).getByText("Moves money")).toBeVisible();
  await teller.getByRole("button", { name: "Start a case" }).click();
  const form = teller.getByRole("dialog", { name: /Start Paper Statement Request/ });
  await form.getByLabel("Customer number").fill(customerNumber);
  await form.getByLabel("Account number").fill(accountNumber);
  await form.getByLabel("Months").fill("3");
  await form.getByLabel("Delivery").selectOption("post");
  await form.getByRole("button", { name: "Start case" }).click();
  const caseView = teller.getByRole("dialog", { name: "Workflow execution" });
  await expect(caseView.getByRole("row", { name: /Approve the paper-statement fee/ }).getByText("waiting")).toBeVisible();
  await expect(caseView.getByRole("row", { name: /Charge the paper-statement fee/ })).toHaveCount(0);

  const manager = await as(browser, "manager", "/workflows?tab=tasks");
  const task = manager.getByRole("listitem").filter({ hasText: "Approve the paper-statement fee" }).filter({ hasText: customerName }).first();
  await task.getByRole("button", { name: /Approve/ }).click();
  await expect(task).toHaveCount(0);
  await manager.getByRole("tab", { name: "Executions" }).click();
  await manager.getByRole("row").filter({ hasText: customerName }).first().click();
  const done = manager.getByRole("dialog", { name: "Workflow execution" });
  await expect(done.getByText("Sent", { exact: true })).toBeVisible();
  await expect(done.getByRole("row", { name: /Charge the paper-statement fee/ })).toContainText("completed");
});
