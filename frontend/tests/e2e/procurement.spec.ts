import { type Browser, expect, type Page, test } from "@playwright/test";

import { signIn } from "./helpers";

async function as(browser: Browser, username: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, username, "/procurement");
  return page;
}

const row = (page: Page, table: string, text: string) => page.getByRole("table", { name: table }).getByRole("row").filter({ hasText: text });

test("Procurement: a vendor is approved by someone else, ordered from, received, invoiced and paid", async ({ browser }) => {
  const clerk = await as(browser, "employee");
  const vendorForm = clerk.getByRole("form", { name: "Register vendor" });
  await vendorForm.getByLabel("Vendor name").fill(`Harbour Office Supplies ${Date.now()}`);
  await vendorForm.getByLabel("Category").selectOption("facilities");
  await vendorForm.getByLabel("Bank account").fill("US000123456789");
  await vendorForm.getByRole("button", { name: "Register vendor" }).click();
  await expect(vendorForm.getByRole("status")).toContainText("low risk");
  const vendor = (await vendorForm.getByRole("status").innerText()).split(" ")[0];
  // The registrant cannot approve it.
  await expect(clerk.getByRole("button", { name: `Approve ${vendor}` })).toHaveCount(0);

  const manager = await as(browser, "manager");
  await manager.getByRole("button", { name: `Approve ${vendor}` }).click();
  await expect(row(manager, "Vendors", vendor)).toContainText("approved");

  await clerk.reload();
  const orderForm = clerk.getByRole("form", { name: "Raise order" });
  await expect(orderForm.getByLabel("Vendor").locator(`option[value="${vendor}"]`)).toHaveCount(1);
  await orderForm.getByLabel("Vendor").selectOption(vendor);
  const department = orderForm.getByLabel("Department");
  await expect(department.locator("option")).not.toHaveCount(1);
  await department.selectOption({ index: 1 });
  await orderForm.getByLabel("Description").fill("Printer paper");
  await orderForm.getByLabel("Quantity").fill("10");
  await orderForm.getByLabel("Unit price").fill("100");
  await orderForm.getByRole("button", { name: "Raise order" }).click();
  await expect(orderForm.getByRole("status")).toContainText("$1,000.00");
  const order = (await orderForm.getByRole("status").innerText()).split(" ")[0];

  await manager.reload();
  await manager.getByRole("button", { name: `Approve ${order}` }).click();
  await expect(row(manager, "Purchase orders", order)).toContainText("approved");

  await clerk.reload();
  await clerk.getByLabel(`Received for ${order}`).fill("1000");
  await clerk.getByRole("button", { name: `Receive ${order}` }).click();
  await expect(row(clerk, "Purchase orders", order)).toContainText("received $1,000.00");
  const invoiceForm = clerk.getByRole("form", { name: "Record invoice" });
  await expect(invoiceForm.getByLabel("Order").locator(`option[value="${order}"]`)).toHaveCount(1);
  await invoiceForm.getByLabel("Order").selectOption(order);
  await invoiceForm.getByLabel("Vendor reference").fill("HOS-1");
  await invoiceForm.getByLabel("Invoice amount").fill("1000");
  await invoiceForm.getByRole("button", { name: "Record invoice" }).click();
  await expect(invoiceForm.getByRole("status")).toContainText("matched");
  const invoice = (await invoiceForm.getByRole("status").innerText()).split(" ")[0];
  // The same vendor reference is never recorded twice.
  await invoiceForm.getByRole("button", { name: "Record invoice" }).click();
  await expect(clerk.getByText(/already/)).toBeVisible();

  await manager.reload();
  await manager.getByRole("button", { name: `Pay ${invoice}` }).click();
  await expect(row(manager, "Invoices", invoice)).toContainText("paid to US000123456789");
  await expect(row(manager, "Purchase orders", order)).toContainText("closed");
});

test("Procurement: a sanctions hit is never approved, and a bank change waits for a second person", async ({ browser }) => {
  const clerk = await as(browser, "employee");
  const vendorForm = clerk.getByRole("form", { name: "Register vendor" });
  await vendorForm.getByLabel("Vendor name").fill("Cyrus Frontcorp");
  await vendorForm.getByLabel("Category").selectOption("marketing");
  await vendorForm.getByLabel("Bank account").fill("US000999999999");
  await vendorForm.getByRole("button", { name: "Register vendor" }).click();
  await expect(vendorForm.getByRole("status")).toContainText("sanctions hit");
  const hit = (await vendorForm.getByRole("status").innerText()).split(" ")[0];

  await vendorForm.getByLabel("Vendor name").fill(`Quay Cleaning ${Date.now()}`);
  await vendorForm.getByLabel("Category").selectOption("facilities");
  await vendorForm.getByLabel("Bank account").fill("US000222222222");
  await vendorForm.getByRole("button", { name: "Register vendor" }).click();
  await expect(vendorForm.getByRole("status")).not.toContainText(hit);
  const vendor = (await vendorForm.getByRole("status").innerText()).split(" ")[0];

  const manager = await as(browser, "manager");
  await manager.getByRole("button", { name: `Approve ${hit}` }).click();
  await expect(manager.getByText(/matches the .* sanctions list/)).toBeVisible();
  await manager.getByRole("button", { name: `Reject ${hit}` }).click();
  await expect(row(manager, "Vendors", hit)).toContainText("rejected");
  await manager.getByRole("button", { name: `Approve ${vendor}` }).click();
  await expect(row(manager, "Vendors", vendor)).toContainText("approved");

  await clerk.reload();
  await clerk.getByLabel(`New bank account for ${vendor}`).fill("US000333333333");
  await clerk.getByRole("button", { name: `Change bank account for ${vendor}` }).click();
  await expect(row(clerk, "Vendors", vendor)).toContainText("change to US000333333333 awaiting checks");
  // The requester cannot verify their own change.
  await expect(clerk.getByRole("button", { name: `Verify bank change for ${vendor}` })).toHaveCount(0);

  await manager.reload();
  await manager.getByRole("button", { name: `Verify bank change for ${vendor}` }).click();
  await expect(row(manager, "Vendors", vendor)).toContainText("pays to US000333333333");
  await expect(row(manager, "Vendors", vendor)).not.toContainText("awaiting checks");
});

test("AI Innovation Lab: the invoice assistant would pay the same bill sent again (its blind spot)", async ({ page }) => {
  // The tool reads procurement data (procurement:read); the administrator has it.
  await signIn(page, "admin", "/ai-lab");
  const registry = page.getByRole("list", { name: "AI tools" });
  await registry.getByRole("button", { name: /AGB Invoice Review Assistant/ }).click();
  const details = page.getByRole("region", { name: "Tool details" });
  await expect(details.getByRole("heading", { name: "AGB Invoice Review Assistant" })).toBeVisible();
  const console = details.getByRole("form", { name: "Test console" });
  await console.getByLabel("Action").selectOption("recommend_decision");
  await console.getByRole("button", { name: "Invoke" }).click();
  await expect(console.getByRole("status")).toContainText("Recommendation: Approve");
});
