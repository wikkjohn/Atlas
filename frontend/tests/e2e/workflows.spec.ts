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
  await expect(importer.getByText(/is valid and can be imported as a draft/)).toBeVisible();
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

test("Templates: the paper-statement template's variants, a preview, and a generated workflow", async ({ browser }) => {
  const admin = await as(browser, "admin", "/workflows?tab=templates");
  await expect(admin.getByRole("list", { name: "Templates" })).toContainText("TPL-PAPER-STATEMENT");
  const variants = admin.getByRole("table", { name: "Template variants" });
  await expect(variants.getByRole("row")).toHaveCount(11); // header + 10 seeded variants

  // A preview of the seeded grid stores nothing and finds every variant unchanged.
  await admin.getByRole("button", { name: "Generate variants" }).click();
  const dialog = admin.getByRole("dialog", { name: "Generate variants of TPL-PAPER-STATEMENT" });
  await dialog.getByLabel("Parameter sets (JSON)").fill(
    JSON.stringify({
      grid: { country_code: ["DE", "GB", "JP", "SG", "US"], account_type: ["current", "savings"] },
      fixed: { fee: 5, approval_permission: "accounts:manage", screen_customers: true },
    }),
  );
  await dialog.getByRole("button", { name: "Preview" }).click();
  await expect(dialog.getByRole("status")).toHaveText("Preview (nothing stored): 0 new, 0 updated, 10 unchanged, 0 invalid");
  await admin.keyboard.press("Escape");

  // Each variant is an ordinary workflow, here Japan's with its own currency.
  await variants.getByRole("row").filter({ hasText: '"country_code":"JP"' }).filter({ hasText: '"current"' }).click();
  await expect(admin.getByText(/Generated from TPL-PAPER-STATEMENT v2/)).toBeVisible(); // v2 classifies its variants
  await expect(admin.getByLabel("Classification")).toContainText("Department: Branch Network · Countries: JP · Products: Current");
  await expect(admin.getByRole("heading", { name: "Paper Statements — Japan, current accounts" })).toBeVisible();
  await expect(admin.getByRole("row", { name: /Charge the paper-statement fee \(5 JPY\)/ })).toContainText("Moves money");
});

test("Generated tests: an administrator runs WF-1002's path tests from the catalogue", async ({ browser }) => {
  const admin = await as(browser, "admin", "/workflows");
  await admin.getByRole("list", { name: "Workflows" }).getByText("Paper Statement Request").click();
  const panel = admin.getByRole("region", { name: "Generated tests" });
  await panel.getByRole("button", { name: "Run tests on v1" }).click();
  await expect(panel.getByRole("status")).toContainText("0 failed · steps 100 % · routes 100 %", { timeout: 30_000 });
  await panel.getByText(/All \d+ cases/).click();
  await expect(panel.getByRole("table", { name: "Test cases" })).toContainText("approval fee_approval: refusals");
});

test("Diagram, editor and review: WF-1001 edited, saved as a draft, tested and approved by a colleague", async ({ browser }) => {
  const admin = await as(browser, "admin", "/workflows");
  await admin.getByRole("list", { name: "Workflows" }).getByText("Paper Statement Request").click();
  await admin.getByRole("tab", { name: "Diagram" }).click();
  const diagram = admin.getByRole("img", { name: /Diagram of WF-1002/ });
  await expect(diagram.locator("text", { hasText: /^Approve the paper-stateme/ })).toBeVisible(); // long names are shortened
  await expect(diagram.getByText("approved", { exact: true })).toBeVisible();
  await expect(diagram.getByText("on failure").first()).toBeVisible();

  await admin.getByRole("list", { name: "Workflows" }).getByText("Customer Address Change").click();
  const edit = admin.getByRole("button", { name: /^Edit as v\d+$/ });
  const label = (await edit.textContent()) ?? "";
  const next = label.replace("Edit as ", "");
  await edit.click();
  const editor = admin.getByRole("dialog", { name: `Edit WF-1001 as ${next}` });
  await expect(editor.getByRole("status")).toHaveText(`Valid: ${next} can be saved as a draft for review.`, { timeout: 15_000 });
  await editor.getByRole("img", { name: /Diagram of WF-1001/ }).locator('[data-step="record_change"]').click();
  const name = editor.getByRole("group", { name: "Step record_change" }).getByLabel("Name");
  await name.fill("Record the new address (edited)");
  await expect(editor.getByRole("img", { name: /Diagram of WF-1001/ })).toContainText("Record the new address (e");
  await expect(editor.getByRole("status")).toHaveText(`Valid: ${next} can be saved as a draft for review.`);
  await editor.getByRole("button", { name: `Save as ${next}` }).click();
  await expect(editor).toHaveCount(0);
  await expect(admin.getByRole("button", { name: `Edit as v${Number(next.slice(1)) + 1}` })).toBeVisible();

  // The new version is a draft: its author submits and tests it, but cannot approve it.
  const versions = admin.getByRole("region", { name: "Versions" });
  await versions.getByRole("button", { name: next, exact: true }).click();
  await versions.getByRole("button", { name: `Submit for review ${next}` }).click();
  const tests = admin.getByRole("region", { name: "Generated tests" });
  await tests.getByRole("button", { name: `Run tests on ${next}` }).click();
  await expect(tests.getByRole("status")).toContainText("0 failed", { timeout: 30_000 });
  await versions.getByRole("button", { name: `Approve ${next}` }).click();
  await expect(versions.getByText(/Four-eyes rule/)).toBeVisible();

  // A department manager approves it; it becomes the active version.
  const manager = await as(browser, "manager", "/workflows");
  await manager.getByRole("list", { name: "Workflows" }).getByText("Customer Address Change").click();
  const review = manager.getByRole("region", { name: "Versions" });
  await review.getByRole("textbox", { name: `Review note for ${next}` }).fill("Renamed step reviewed.");
  await review.getByRole("button", { name: `Approve ${next}` }).click();
  await expect(review.getByRole("listitem").filter({ hasText: `“Renamed step reviewed.”` })).toContainText("Active");
});

test("Catalogue: generated variants found by country and product facets", async ({ browser }) => {
  const page = await as(browser, "employee", "/workflows");
  await page.getByRole("combobox", { name: "Filter by country" }).selectOption("JP");
  await page.getByRole("combobox", { name: "Filter by product" }).selectOption("savings");
  await page.getByRole("combobox", { name: "Filter by department" }).selectOption("Branch Network");
  const list = page.getByRole("list", { name: "Workflows" });
  await expect(list.getByRole("button")).toHaveCount(1);
  await expect(list).toContainText("TPL-PAPER-STATEMENT");
  await list.getByRole("button").click();
  await expect(page.getByLabel("Classification")).toContainText("Countries: JP · Products: Savings");
});
