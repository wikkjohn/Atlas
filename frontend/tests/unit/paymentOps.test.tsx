import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { BulkFile, ClearingBatch, OutgoingPayment, Recall } from "@/types/paymentOps";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const payment = (overrides: Partial<OutgoingPayment>): OutgoingPayment => ({
  id: "opy-1",
  payment_number: "OPY-00000001",
  account_number: "GB000000000101",
  beneficiary_name: "Synthetic Supplier Ltd",
  beneficiary_bank: "NBKAGB22",
  beneficiary_account: "12345678901218",
  amount: 250_000,
  currency: "GBP",
  reference: "Invoice 42",
  status: "settled",
  high_value: false,
  bulk_file_id: null,
  return_code: null,
  reason: null,
  settled_on: "2026-10-31",
  created_at: "2026-10-31T09:00:00Z",
  ...overrides,
});
const awaiting = payment({ id: "opy-2", payment_number: "OPY-00000002", status: "awaiting_approval", high_value: true, amount: 5_000_000, settled_on: null });
const returned = payment({ id: "opy-3", payment_number: "OPY-00000003", status: "returned", return_code: "AC04", reason: "The beneficiary's bank has closed the account." });
const batch: ClearingBatch = {
  id: "clb-1",
  batch_number: "CLB-0000001",
  currency: "GBP",
  business_date: "2026-10-31",
  payments: 2,
  total: 500_000,
  settled_count: 1,
  returned_count: 1,
  status: "settled",
  created_at: "2026-10-31T10:00:00Z",
};
const bulk: BulkFile = {
  id: "blk-1",
  file_number: "BLK-0000001",
  account_number: "GB000000000555",
  file_name: "october.csv",
  currency: "GBP",
  lines: [
    { line: 1, name: "Supplier A", bank: "ALPEDEFF", account: "12345678901218", amount: 100_000, reference: "" },
    { line: 2, name: "Supplier B", bank: "LACBFRPP", account: "12345678901299", amount: 50_000, reference: "", error: "The beneficiary account's check digits are wrong." },
  ],
  valid_count: 1,
  invalid_count: 1,
  valid_total: 100_000,
  status: "received",
  decision_note: null,
  created_at: "2026-10-31T09:30:00Z",
};
const recalls: Recall[] = [
  { id: "rcl-1", recall_number: "RCL-0000001", payment_number: "OPY-00000001", reason_code: "DUPL", status: "requested", outcome_note: null, created_at: "2026-10-31T11:00:00Z" },
  { id: "rcl-2", recall_number: "RCL-0000002", payment_number: "OPY-00000004", reason_code: "FRAD", status: "sent", outcome_note: null, created_at: "2026-10-31T11:05:00Z" },
];

const routes = {
  ...healthyRoutes,
  "GET /api/v1/payment-ops/summary/counts": () => jsonResponse({ awaiting_approval: 1, pending: 0, returned: 1, bulk_received: 1, open_recalls: 2 }),
  "GET /api/v1/payment-ops/banks": () => jsonResponse([{ code: "NBKAGB22", name: "Northbank Retail (synthetic)" }, { code: "RIVRUS33", name: "Riverside Savings (synthetic)" }]),
  "GET /api/v1/payment-ops/payments": () => jsonResponse(page([payment({}), awaiting, returned])),
  "GET /api/v1/payment-ops/batches": () => jsonResponse(page([batch])),
  "GET /api/v1/payment-ops/bulk": () => jsonResponse(page([bulk])),
  "GET /api/v1/payment-ops/recalls": () => jsonResponse(page(recalls)),
};

describe("Payments Operations page", () => {
  it("shows payments, returns, batches, bulk files and recalls", async () => {
    mockApi(routes);
    renderApp("/payment-ops");
    const outgoing = await screen.findByRole("table", { name: "Outgoing payments" });
    const row = (await within(outgoing).findByText("OPY-00000003")).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("AC04: The beneficiary's bank has closed the account.");
    expect(within(outgoing).getByText("OPY-00000001").closest("tr")).toHaveTextContent("£2,500.00");
    expect(screen.getByRole("table", { name: "Clearing batches" })).toHaveTextContent("2 payments · 1 settled, 1 returned");
    expect(screen.getByRole("table", { name: "Bulk files" })).toHaveTextContent("1 valid, 1 invalid (line 2: The beneficiary account's check digits are wrong.)");
    expect(screen.getByRole("table", { name: "Recalls" })).toHaveTextContent("OPY-00000004 · Fraud");
  });

  it("sends, approves, runs a cycle, receives and releases a bulk file and handles recalls", async () => {
    const api = mockApi({
      ...routes,
      "GET /api/v1/accounts": () => jsonResponse(page([{ account_number: "JP000000000900", currency: "JPY" }, { account_number: "GB000000000555", currency: "GBP" }])),
      "POST /api/v1/payment-ops/payments": () => jsonResponse(payment({ id: "opy-9", status: "pending" }), 201),
      "POST /api/v1/payment-ops/payments/opy-2/approve": () => jsonResponse({ ...awaiting, status: "pending" }),
      "POST /api/v1/payment-ops/cycles": () => jsonResponse({ batch }),
      "POST /api/v1/payment-ops/bulk": () => jsonResponse({ ...bulk, id: "blk-2", file_number: "BLK-0000002" }, 201),
      "POST /api/v1/payment-ops/bulk/blk-1/release": () => jsonResponse({ ...bulk, status: "released" }),
      "POST /api/v1/payment-ops/recalls": () => jsonResponse({ ...recalls[0], id: "rcl-9" }, 201),
      "POST /api/v1/payment-ops/recalls/rcl-1/approve": () => jsonResponse({ ...recalls[0], status: "accepted" }),
      "POST /api/v1/payment-ops/recalls/rcl-2/resolve": () => jsonResponse({ ...recalls[1], status: "refused" }),
    });
    renderApp("/payment-ops");
    const form = await screen.findByRole("form", { name: "Pay another bank" });
    await userEvent.type(within(form).getByLabelText("From account"), "JP000000000900");
    await userEvent.type(within(form).getByLabelText("Beneficiary name"), "Kitsune Trading");
    await waitFor(() => expect(within(form).getByRole("option", { name: /RIVRUS33/ })).toBeInTheDocument());
    await userEvent.selectOptions(within(form).getByLabelText("Beneficiary bank"), "RIVRUS33");
    await userEvent.type(within(form).getByLabelText("Beneficiary account"), "12345678901218");
    await userEvent.type(within(form).getByLabelText("Amount"), "15000");
    await userEvent.click(within(form).getByRole("button", { name: "Send" }));

    await userEvent.click(screen.getByRole("button", { name: "Approve OPY-00000002" }));
    const cycle = screen.getByRole("form", { name: "Run a clearing cycle" });
    await userEvent.type(within(cycle).getByLabelText("Cycle currency"), "gbp");
    await userEvent.click(within(cycle).getByRole("button", { name: "Run cycle" }));

    const file = screen.getByRole("form", { name: "Bulk file" });
    await userEvent.type(within(file).getByLabelText("Bulk account"), "GB000000000555");
    await userEvent.type(within(file).getByLabelText("Lines"), "Supplier A, alpedeff, 12345678901218, 1000.50, Invoice 7");
    await userEvent.click(within(file).getByRole("button", { name: "Receive file" }));
    await userEvent.click(screen.getByRole("button", { name: "Release BLK-0000001" }));

    const recall = screen.getByRole("form", { name: "Recall a payment" });
    await userEvent.type(within(recall).getByLabelText("Payment number"), "opy-00000001");
    await userEvent.click(within(recall).getByRole("button", { name: "Request recall" }));
    await userEvent.click(screen.getByRole("button", { name: "Approve RCL-0000001" }));
    await userEvent.click(screen.getByRole("button", { name: "Record answer RCL-0000002" }));

    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(8));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/payment-ops/payments"]).toEqual({
      account_number: "JP000000000900",
      beneficiary_name: "Kitsune Trading",
      beneficiary_bank: "RIVRUS33",
      beneficiary_account: "12345678901218",
      amount: 15_000, // yen have no minor unit
      reference: "",
    });
    expect(bodies["POST /api/v1/payment-ops/cycles"]).toEqual({ currency: "GBP" });
    expect(bodies["POST /api/v1/payment-ops/bulk"]).toEqual({
      account_number: "GB000000000555",
      file_name: "bulk",
      lines: [{ name: "Supplier A", bank: "ALPEDEFF", account: "12345678901218", amount: 100_050, reference: "Invoice 7" }],
    });
    expect(bodies["POST /api/v1/payment-ops/recalls"]).toEqual({ payment_number: "OPY-00000001", reason_code: "DUPL" });
  });

  it("is read-only without the payments permissions", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["payments:read"] }) });
    renderApp("/payment-ops");
    expect(await screen.findByText("OPY-00000002")).toBeInTheDocument();
    for (const name of ["Pay another bank", "Run a clearing cycle", "Bulk file", "Recall a payment"]) {
      expect(screen.queryByRole("form", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: /^Approve / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Record answer / })).not.toBeInTheDocument();
  });
});
