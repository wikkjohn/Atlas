import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { MonthEndRun, RetailProduct, StandingOrder, Statement } from "@/types/retail";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const products: RetailProduct[] = [
  { account_type: "current", name: "Everyday Current Account", credit_rate_bps: 0, overdraft_rate_bps: 1990, monthly_fee_usd_cents: 500, max_overdraft_usd: 2500, updated_at: "2026-10-30T00:00:00Z" },
  { account_type: "savings", name: "Instant Access Savings", credit_rate_bps: 250, overdraft_rate_bps: 0, monthly_fee_usd_cents: 0, max_overdraft_usd: 0, updated_at: "2026-10-30T00:00:00Z" },
];
const order: StandingOrder = {
  id: "so-1",
  order_number: "SO-0000001",
  debtor_account_number: "GB000000000101",
  creditor_account_number: "GB000000000102",
  amount: 75_000,
  currency: "GBP",
  frequency: "monthly",
  next_date: "2026-11-01",
  end_date: null,
  reference: "Rent",
  status: "active",
  failures: 0,
  last_error: null,
  payments_made: 2,
  created_at: "2026-09-01T00:00:00Z",
};
const statement: Statement = {
  id: "st-1",
  statement_number: "STM-0000007",
  account_id: "acc-1",
  account_number: "GB000000000101",
  period_start: "2026-09-01",
  period_end: "2026-09-30",
  currency: "GBP",
  opening_balance: 100_000,
  closing_balance: 24_500,
  total_credits: 0,
  total_debits: 75_500,
  lines: 2,
  overdraft_limit: 0,
  issued_at: "2026-10-01T00:00:00Z",
};
const run: MonthEndRun = {
  id: "me-1",
  period_start: "2026-09-01",
  period_end: "2026-09-30",
  accounts: 12,
  statements: 12,
  entries: 9,
  totals: { GBP: { interest_paid: 1234, interest_charged: 87, fees: 2000 } },
  completed_at: "2026-10-01T00:00:00Z",
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/retail/summary": () => jsonResponse({ overdrafts: 3, active_standing_orders: 1, statements: 12 }),
  "GET /api/v1/retail/products": () => jsonResponse(products),
  "GET /api/v1/retail/standing-orders": () => jsonResponse(page([order])),
  "GET /api/v1/retail/statements": () => jsonResponse(page([statement])),
  "GET /api/v1/retail/month-ends": () => jsonResponse([run]),
  "GET /api/v1/retail/statements/st-1": () =>
    jsonResponse({
      ...statement,
      entries: [
        { date: "2026-09-01", entry_number: "JE-0000100", description: "Payment SO-0000001 Rent", source: "payment", amount: -75_000, balance: 25_000 },
        { date: "2026-09-30", entry_number: "JE-0000140", description: "Everyday Current Account monthly fee", source: "fee", amount: -500, balance: 24_500 },
      ],
    }),
};

describe("Retail Banking page", () => {
  it("shows products, standing orders, month ends and a statement", async () => {
    mockApi(routes);
    renderApp("/retail");

    expect(await screen.findByText("Everyday Current Account")).toBeInTheDocument();
    const products = screen.getByRole("table", { name: "Retail products" });
    expect(within(products).getByText("19.90 %")).toBeInTheDocument();
    expect(within(products).getByText("2.50 %")).toBeInTheDocument();
    expect(within(products).getByText("$2,500.00")).toBeInTheDocument();
    const summary = (await screen.findByText("Arranged overdrafts")).closest("div") as HTMLElement;
    expect(within(summary).getByText("3")).toBeInTheDocument();
    const orders = screen.getByRole("table", { name: "Standing orders" });
    expect(await within(orders).findByText("SO-0000001")).toBeInTheDocument();
    expect(within(orders).getByText(/Rent · monthly · next 2026-11-01 · 2 paid/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Month-end runs" })).toHaveTextContent("12 accounts · 9 postings · 12 statements");

    await userEvent.click(await screen.findByRole("button", { name: "STM-0000007" }));
    const dialog = await screen.findByRole("dialog", { name: "Statement STM-0000007" });
    expect(await within(dialog).findByText("Everyday Current Account monthly fee")).toBeInTheDocument();
  });

  it("lets a manager change terms, set up and cancel standing orders and run month end", async () => {
    const api = mockApi({
      ...routes,
      "PATCH /api/v1/retail/products/savings": () => jsonResponse({ ...products[1], credit_rate_bps: 300 }),
      "POST /api/v1/retail/standing-orders": () => jsonResponse({ ...order, id: "so-2", order_number: "SO-0000002" }, 201),
      "POST /api/v1/retail/standing-orders/so-1/cancel": () => jsonResponse({ ...order, status: "cancelled" }),
      "POST /api/v1/retail/month-ends": () => jsonResponse({ id: "job-1", job_number: 5, status: "queued" }, 202),
    });
    renderApp("/retail");

    await userEvent.click(await screen.findByRole("button", { name: "Edit Instant Access Savings" }));
    const credit = screen.getByLabelText("Credit interest (bps) of Instant Access Savings");
    await userEvent.clear(credit);
    await userEvent.type(credit, "300");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const form = screen.getByRole("form", { name: "New standing order" });
    await userEvent.type(within(form).getByLabelText("Payer account"), "GB000000000101");
    await userEvent.type(within(form).getByLabelText("Payee account"), "GB000000000102");
    await userEvent.type(within(form).getByLabelText("Amount"), "750.50");
    await userEvent.type(within(form).getByLabelText("Reference"), "Rent");
    await userEvent.type(within(form).getByLabelText("First payment"), "2026-11-01");
    await userEvent.click(within(form).getByRole("button", { name: "Set up" }));

    await userEvent.click(await screen.findByRole("button", { name: "Cancel SO-0000001" }));
    await userEvent.click(screen.getByRole("button", { name: "Run month end" }));
    expect(await screen.findByText("Job #5 queued for the last complete month.")).toBeInTheDocument();

    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(4));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["PATCH /api/v1/retail/products/savings"]).toEqual({ credit_rate_bps: 300, overdraft_rate_bps: 0, monthly_fee_usd_cents: 0 });
    expect(bodies["POST /api/v1/retail/standing-orders"]).toEqual({
      debtor_account_number: "GB000000000101",
      creditor_account_number: "GB000000000102",
      amount: 75_050,
      frequency: "monthly",
      first_date: "2026-11-01",
      reference: "Rent",
    });
  });

  it("is read-only without the permissions", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["accounts:read"] }) });
    renderApp("/retail");
    expect(await screen.findByText("Everyday Current Account")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Edit / })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "New standing order" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run month end" })).not.toBeInTheDocument();
  });
});
