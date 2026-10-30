import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Account, Payment } from "@/types/banking";
import type { ExecutionDetail, WorkflowDefinition } from "@/types/workflows";

import { account, loan } from "./banking-fixtures";
import { healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const payee: Account = { ...account, id: "acc-2", account_number: "US000000004351", customer_id: "cus-3", customer_name: "Ines Costa", balance: 0 };
const euro: Account = { ...account, id: "acc-3", account_number: "DE000000004444", customer_name: "Jonas Weber", currency: "EUR" };
const funded: Account = { ...account, balance: 250_000 };

const payment = (partial: Partial<Payment>): Payment => ({
  id: "pay-1",
  payment_number: "PAY-00000001",
  debtor_account_number: funded.account_number,
  debtor_name: funded.customer_name,
  creditor_account_number: payee.account_number,
  creditor_name: payee.customer_name,
  amount: 125_050,
  currency: "USD",
  reference: "Invoice 1042",
  status: "released",
  high_value: false,
  initiated_by_username: "employee",
  approved_by_username: null,
  journal_entry_id: "je-1",
  rejection_reason: null,
  workflow_execution_id: "exe-1",
  created_at: "2026-10-28T10:00:00Z",
  decided_at: "2026-10-28T10:00:01Z",
  ...partial,
});


describe("Payments and lending", () => {
  it("lists payments with their outcome and approver", async () => {
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/payments": () =>
        jsonResponse(
          page([
            payment({}),
            payment({ id: "pay-2", payment_number: "PAY-00000002", status: "rejected", rejection_reason: "Declined at fraud review: scam", journal_entry_id: null }),
            payment({ id: "pay-3", payment_number: "PAY-00000003", amount: 2_000_000, high_value: true, approved_by_username: "manager" }),
          ]),
        ),
    });
    renderApp("/payments");

    await screen.findByText("PAY-00000001");
    const table = screen.getByRole("table", { name: "Payments" });
    const first = within(table).getByText("PAY-00000001").closest("tr") as HTMLElement;
    expect(within(first).getByText("$1,250.50")).toBeInTheDocument();
    expect(within(first).getByText("Straight-through")).toBeInTheDocument();
    expect(within(first).getByRole("link", { name: "Workflow case" })).toHaveAttribute("href", "/workflows?tab=executions&execution=exe-1");
    const rejected = within(table).getByText("PAY-00000002").closest("tr") as HTMLElement;
    expect(within(rejected).getByText("Declined at fraud review: scam")).toBeInTheDocument();
    const big = within(table).getByText("PAY-00000003").closest("tr") as HTMLElement;
    expect(within(big).getByText("High value")).toBeInTheDocument();
    expect(within(big).getByText("manager")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Rejected" }));
    await waitFor(() => expect(api.requests.some((r) => r.search.get("status") === "rejected")).toBe(true));
  }, 20_000);

  it("lists loans with pricing, balance and approvals", async () => {
    mockApi({
      ...healthyRoutes,
      "GET /api/v1/loans": () => jsonResponse(page([loan])),
      "GET /api/v1/loans/servicing-runs": () => jsonResponse(page([])),
    });
    renderApp("/lending");

    const row = (await screen.findByText("LN-00000001")).closest("tr") as HTMLElement;
    expect(within(row).getByText("6.90 % · 36 mo")).toBeInTheDocument();
    expect(within(row).getByText("$308.31")).toBeInTheDocument();
    expect(within(row).getAllByText("$10,000.00")).toHaveLength(2); // principal and outstanding
    expect(within(row).getByText("Underwriter: manager")).toBeInTheDocument();
  });
});

const workflow = (id: string, name: string): WorkflowDefinition => ({
  workflow_id: id,
  name,
  version: 1,
  versions: [1],
  description: name,
  business_owner: "Payments Operations",
  trigger_type: "api",
  step_count: 1,
  source: "code",
  status: "active",
  start: "complete",
  input_schema: {},
  steps: [{ id: "complete", type: "completion", name: "Closed" }],
  transition_rules: [],
  approval_policies: [],
  failure_policies: [],
  timeout_policies: [],
});

const started: ExecutionDetail = {
  id: "new-1",
  workflow_id: "WF-0002",
  workflow_version: 1,
  status: "completed",
  outcome: "approved",
  current_steps: [],
  business_key: "PAY-00000009",
  subject: "$1,250.50 to US000000004351",
  initiated_by: "u1",
  initiated_by_username: "admin",
  correlation_id: null,
  started_at: "2026-10-28T10:00:00Z",
  completed_at: "2026-10-28T10:00:01Z",
  duration_ms: 1000,
  context: { input: {} },
  error: null,
  steps: [],
};

function startRoutes(id: string, name: string) {
  return {
    ...healthyRoutes,
    "GET /api/v1/workflow-catalogue": () => jsonResponse({ items: [workflow(id, name)], total: 1, facets: {} }),
    [`GET /api/v1/workflows/${id}`]: () => jsonResponse(workflow(id, name)),
    [`GET /api/v1/workflows/${id}/metrics`]: () =>
      jsonResponse({ workflow_id: id, executions: {}, outcomes: {}, avg_execution_ms: null, bottleneck_step: null, steps: [] }),
    "GET /api/v1/accounts": () => jsonResponse(page([funded, payee, euro])),
    [`POST /api/v1/workflows/${id}/executions`]: () => jsonResponse({ ...started, workflow_id: id }, 201),
    "GET /api/v1/workflow-executions": () => jsonResponse(page([])),
    "GET /api/v1/workflow-executions/new-1": () => jsonResponse({ ...started, workflow_id: id }),
    "GET /api/v1/workflow-executions/new-1/history": () => jsonResponse([]),
    "POST /api/v1/fx/quote": () =>
      jsonResponse({ sell_currency: "USD", sell_amount: 125_050, buy_currency: "EUR", buy_amount: 107_237, mid_rate: "0.8618", customer_rate: "0.857533092082", margin_bps: 50, rate_date: "2026-03-02", base_amount: 125_050 }),
  };
}

describe("Starting payments and loan applications", () => {
  it("sends a payment in minor units, and estimates the conversion for a payee in another currency", async () => {
    const api = mockApi(startRoutes("WF-0002", "Domestic Payment"));
    renderApp("/workflows");

    await userEvent.click(await screen.findByRole("button", { name: "Start a payment" }));
    const dialog = screen.getByRole("dialog");
    const paying = within(dialog).getByLabelText("Paying account");
    await userEvent.selectOptions(paying, await within(paying).findByRole("option", { name: /US000000004257/ }));
    const payees = within(within(dialog).getByLabelText("Payee account")).getAllByRole("option").map((o) => o.textContent);
    // Not itself; a payee in another currency is paid after conversion (Phase 24).
    expect(payees).toEqual(["Select…", "US000000004351 · Ines Costa (USD)", "DE000000004444 · Jonas Weber (EUR)"]);
    await userEvent.type(within(dialog).getByLabelText("Search payees"), "Costa");
    await waitFor(() => expect(api.requests.some((r) => r.path === "/api/v1/accounts" && r.search.get("q") === "Costa")).toBe(true));
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit payment" }));
    expect(within(dialog).getByText("Enter an amount above zero.")).toBeInTheDocument();
    expect(api.requests.some((r) => r.method === "POST" && r.path.endsWith("/executions"))).toBe(false);

    await userEvent.type(within(dialog).getByLabelText("Amount (USD)"), "1250.50");
    await userEvent.selectOptions(within(dialog).getByLabelText("Payee account"), "DE000000004444");
    expect(await within(dialog).findByLabelText("Conversion estimate")).toHaveTextContent("The payee receives about €1,072.37 at today's rate (0.857533, 0.5 % margin)");
    await userEvent.selectOptions(within(dialog).getByLabelText("Payee account"), "US000000004351");
    expect(within(dialog).queryByLabelText("Conversion estimate")).not.toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("Reference"), "Invoice 1042");
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit payment" }));

    await screen.findByRole("dialog", { name: "Workflow execution" });
    const post = api.requests.find((r) => r.method === "POST" && r.path.endsWith("/executions"));
    expect(post?.body).toEqual({
      input: {
        debtor_account_number: "US000000004257",
        creditor_account_number: "US000000004351",
        amount: 125_050,
        currency: "USD",
        reference: "Invoice 1042",
        channel: "branch",
      },
    });
    expect(post?.headers["Idempotency-Key"]).toBeTruthy();
  }, 20_000);

  it("sends a loan application for the chosen customer's account", async () => {
    const api = mockApi(startRoutes("WF-0003", "Personal Loan Origination"));
    renderApp("/workflows");

    await userEvent.click(await screen.findByRole("button", { name: "Start a loan application" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.selectOptions(
      within(dialog).getByLabelText("Customer and disbursement account"),
      await within(dialog).findByRole("option", { name: /Ines Costa/ }),
    );
    await userEvent.type(within(dialog).getByLabelText("Amount (USD)"), "12000");
    await userEvent.type(within(dialog).getByLabelText("Monthly income (USD)"), "5000");
    await userEvent.selectOptions(within(dialog).getByLabelText("Term"), "48");
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit application" }));

    await screen.findByRole("dialog", { name: "Workflow execution" });
    expect(api.requests.some((r) => r.path === "/api/v1/accounts" && r.search.get("account_type") === "current")).toBe(true);
    expect(api.requests.find((r) => r.method === "POST")?.body).toEqual({
      input: {
        customer_number: "CUS-0000002",
        disbursement_account_number: "US000000004351",
        amount: 1_200_000,
        term_months: 48,
        purpose: "home_improvement",
        monthly_income: 500_000,
        monthly_debt_payments: 0,
        employment_status: "employed",
      },
    });
  }, 20_000);
});
