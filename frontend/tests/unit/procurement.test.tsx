import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ProcurementDepartment, PurchaseOrder, Vendor, VendorInvoice } from "@/types/procurement";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const dept: ProcurementDepartment = { id: "dep-1", name: "Customer Onboarding", country: "US", currency: "USD" };
const vendor: Vendor = {
  id: "ven-1",
  vendor_number: "VEN-000001",
  name: "Harbour Office Supplies",
  country: "US",
  currency: "USD",
  category: "facilities",
  bank_account: "US000123456789",
  pending_bank_account: null,
  risk_tier: "low",
  sanctions_hit: false,
  status: "approved",
  created_at: "2026-11-02T09:00:00Z",
};
const pendingVendor: Vendor = { ...vendor, id: "ven-2", vendor_number: "VEN-000002", name: "Cyrus Frontcorp", category: "marketing", status: "pending", sanctions_hit: true };
const changing: Vendor = { ...vendor, id: "ven-3", vendor_number: "VEN-000003", name: "Meridian Outsourcing", risk_tier: "high", pending_bank_account: "US000987654321" };
const order: PurchaseOrder = {
  id: "po-1",
  order_number: "PO-0000001",
  vendor_number: "VEN-000001",
  vendor_name: "Harbour Office Supplies",
  department: "Customer Onboarding",
  description: "Printer paper",
  lines: [{ description: "Printer paper", quantity: 10, unit_price: 10_000 }],
  total: 100_000,
  total_usd: 1_000,
  currency: "USD",
  received_amount: 60_000,
  invoiced: 0,
  status: "received",
  created_at: "2026-11-02T09:00:00Z",
};
const requested: PurchaseOrder = { ...order, id: "po-2", order_number: "PO-0000002", received_amount: 0, status: "requested" };
const invoice: VendorInvoice = {
  id: "inv-1",
  invoice_number: "INV-0000001",
  vendor_reference: "HOS-1",
  order_number: "PO-0000001",
  vendor_name: "Harbour Office Supplies",
  amount: 60_000,
  currency: "USD",
  invoice_date: "2026-11-02",
  status: "recorded",
  hold_reason: null,
  paid_to: null,
  entry_number: null,
  created_at: "2026-11-02T09:00:00Z",
};
const held: VendorInvoice = { ...invoice, id: "inv-2", invoice_number: "INV-0000002", vendor_reference: "HOS-2", status: "held", hold_reason: "Invoiced would exceed the 60000 received by more than 2 %." };

const routes = {
  ...healthyRoutes,
  "GET /api/v1/procurement/summary/counts": () =>
    jsonResponse({ vendors_to_approve: 1, vendors_approved: 2, bank_changes_to_verify: 1, orders_to_approve: 1, orders_open: 1, invoices_to_pay: 1, invoices_held: 1 }),
  "GET /api/v1/procurement/departments": () => jsonResponse([dept]),
  "GET /api/v1/procurement/vendors": () => jsonResponse(page([vendor, pendingVendor, changing])),
  "GET /api/v1/procurement/orders": () => jsonResponse(page([order, requested])),
  "GET /api/v1/procurement/invoices": () => jsonResponse(page([invoice, held])),
};

describe("Procurement page", () => {
  it("shows the summary, vendors with their screening and bank changes, orders and invoices", async () => {
    mockApi(routes);
    renderApp("/procurement");
    expect(await screen.findByLabelText("Procurement summary")).toHaveTextContent("Bank changes to verify1");
    const vendors = await screen.findByRole("table", { name: "Vendors" });
    expect((await within(vendors).findByText("VEN-000002")).closest("tr")).toHaveTextContent("sanctions hit");
    expect(within(vendors).getByText("VEN-000003").closest("tr")).toHaveTextContent("change to US000987654321 awaiting checks");
    expect(within(vendors).getByText("VEN-000003").closest("tr")).toHaveTextContent("high risk");
    expect((await screen.findByText("PO-0000001")).closest("tr")).toHaveTextContent("received $600.00");
    expect((await screen.findByText("INV-0000002")).closest("tr")).toHaveTextContent("exceed");
    expect(screen.queryByRole("button", { name: "Pay INV-0000002" })).not.toBeInTheDocument();
  });

  it("registers and approves vendors, verifies a bank change, raises and receives orders, and records and pays invoices", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/procurement/vendors": () => jsonResponse({ ...pendingVendor, id: "ven-4", vendor_number: "VEN-000004", sanctions_hit: false, name: "Quay Cleaning" }, 201),
      "POST /api/v1/procurement/vendors/ven-2/reject": () => jsonResponse({ ...pendingVendor, status: "rejected" }),
      "POST /api/v1/procurement/vendors/ven-3/bank-change/verify": () => jsonResponse({ ...changing, bank_account: "US000987654321", pending_bank_account: null }),
      "POST /api/v1/procurement/orders": () => jsonResponse({ ...requested, id: "po-3", order_number: "PO-0000003", total: 50_000 }, 201),
      "POST /api/v1/procurement/orders/po-1/receive": () => jsonResponse({ ...order, received_amount: 100_000 }),
      "POST /api/v1/procurement/invoices": () => jsonResponse({ ...invoice, id: "inv-3", invoice_number: "INV-0000003" }, 201),
      "POST /api/v1/procurement/invoices/inv-1/pay": () => jsonResponse({ ...invoice, status: "paid", paid_to: "US000123456789", entry_number: "JE-1" }),
    });
    renderApp("/procurement");
    const vendorForm = await screen.findByRole("form", { name: "Register vendor" });
    await userEvent.type(within(vendorForm).getByLabelText("Vendor name"), "Quay Cleaning");
    await userEvent.selectOptions(within(vendorForm).getByLabelText("Category"), "facilities");
    await userEvent.type(within(vendorForm).getByLabelText("Bank account"), "US000555555555");
    await userEvent.click(within(vendorForm).getByRole("button", { name: "Register vendor" }));
    expect(await within(vendorForm).findByRole("status")).toHaveTextContent("VEN-000004 registered: low risk");
    await userEvent.click(await screen.findByRole("button", { name: "Reject VEN-000002" }));
    await userEvent.click(screen.getByRole("button", { name: "Verify bank change for VEN-000003" }));

    const orderForm = screen.getByRole("form", { name: "Raise order" });
    await within(within(orderForm).getByLabelText("Vendor")).findByRole("option", { name: /VEN-000001/ });
    await userEvent.selectOptions(within(orderForm).getByLabelText("Vendor"), "VEN-000001");
    await within(within(orderForm).getByLabelText("Department")).findByRole("option", { name: /Customer Onboarding/ });
    await userEvent.selectOptions(within(orderForm).getByLabelText("Department"), "dep-1");
    await userEvent.type(within(orderForm).getByLabelText("Description"), "Toner");
    await userEvent.clear(within(orderForm).getByLabelText("Quantity"));
    await userEvent.type(within(orderForm).getByLabelText("Quantity"), "5");
    await userEvent.type(within(orderForm).getByLabelText("Unit price"), "100");
    await userEvent.click(within(orderForm).getByRole("button", { name: "Raise order" }));
    expect(await within(orderForm).findByRole("status")).toHaveTextContent("PO-0000003 raised");
    await userEvent.type(screen.getByLabelText("Received for PO-0000001"), "400");
    await userEvent.click(screen.getByRole("button", { name: "Receive PO-0000001" }));

    const invoiceForm = screen.getByRole("form", { name: "Record invoice" });
    await userEvent.selectOptions(within(invoiceForm).getByLabelText("Order"), "PO-0000001");
    await userEvent.type(within(invoiceForm).getByLabelText("Vendor reference"), "HOS-3");
    await userEvent.type(within(invoiceForm).getByLabelText("Invoice amount"), "400");
    await userEvent.click(within(invoiceForm).getByRole("button", { name: "Record invoice" }));
    expect(await within(invoiceForm).findByRole("status")).toHaveTextContent("INV-0000003 matched");
    await userEvent.click(screen.getByRole("button", { name: "Pay INV-0000001" }));

    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(7));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/procurement/vendors"]).toMatchObject({ name: "Quay Cleaning", country: "US", category: "facilities", bank_account: "US000555555555" });
    expect(bodies["POST /api/v1/procurement/orders"]).toMatchObject({
      vendor_number: "VEN-000001",
      department_id: "dep-1",
      lines: [{ description: "Toner", quantity: 5, unit_price: 10_000 }],
    });
    expect(bodies["POST /api/v1/procurement/orders/po-1/receive"]).toMatchObject({ amount: 40_000 });
    expect(bodies["POST /api/v1/procurement/invoices"]).toMatchObject({ order_number: "PO-0000001", vendor_reference: "HOS-3", amount: 40_000 });
  });

  it("is read-only with only procurement:read", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["procurement:read"] }) });
    renderApp("/procurement");
    expect(await screen.findByText("VEN-000002")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Register vendor" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Raise order" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve VEN-000002" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pay INV-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Receive PO-0000001" })).not.toBeInTheDocument();
  });
});
