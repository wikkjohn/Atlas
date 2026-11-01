import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { CostAllocation, ManualJournal, PeriodClose, RegulatoryReport } from "@/types/finance";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const prepared: PeriodClose = {
  id: "cls-1",
  close_number: "CLS-0000002",
  period: "2026-10",
  period_start: "2026-10-01",
  period_end: "2026-10-31",
  status: "prepared",
  checks: [
    { check: "period_ended", passed: true, blocking: true, detail: "The month ended on 2026-10-31." },
    { check: "trial_balance", passed: true, blocking: true, detail: "Debits equal credits." },
    { check: "reconciliation", passed: true, blocking: true, detail: "Passed." },
    { check: "provisions_posted", passed: false, blocking: false, detail: "No ECL run (advisory)." },
  ],
  results: { USD: { income: 250_000, expense: 100_000, net_income: 150_000, accounts: [] } },
  note: null,
  created_at: "2026-11-01T09:00:00Z",
};
const report: RegulatoryReport = {
  id: "reg-1",
  report_number: "REG-0000001",
  report_type: "balance_sheet",
  period: "2026-09",
  status: "prepared",
  rows: [{ currency: "USD", line: "asset", amount: 900_000 }],
  summary: {},
  reference: null,
  note: null,
  created_at: "2026-11-01T09:10:00Z",
};
const allocation: CostAllocation = {
  id: "alc-1",
  allocation_number: "ALC-0000001",
  period: "2026-11",
  currency: "USD",
  pool: 100_000,
  driver: "headcount",
  lines: [
    { department_id: "d1", department: "Retail Operations", headcount: 3, amount: 75_000, account_code: "FIN-COST-D1-USD" },
    { department_id: "d2", department: "Treasury", headcount: 1, amount: 25_000, account_code: "FIN-COST-D2-USD" },
  ],
  status: "calculated",
  note: null,
  created_at: "2026-11-01T09:20:00Z",
};

const journal: ManualJournal = {
  id: "mj-1",
  journal_number: "MJ-0000001",
  currency: "USD",
  effective_date: "2026-11-01",
  description: "Accrual for legal fees",
  lines: [
    { account_code: "FIN-SHARED-COSTS-USD", direction: "debit", amount: 250_000 },
    { account_code: "FIN-ACCRUALS-USD", direction: "credit", amount: 250_000 },
  ],
  amount: 250_000,
  status: "proposed",
  entry_number: null,
  note: null,
  created_at: "2026-11-01T09:30:00Z",
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/finance/summary/counts": () =>
    jsonResponse({ last_closed_period: "2026-09", next_period: "2026-10", closes_to_approve: 1, reports_to_submit: 1, reports_submitted: 0, allocations_to_post: 1, journals_to_approve: 1 }),
  "GET /api/v1/finance/closes": () => jsonResponse(page([prepared])),
  "GET /api/v1/finance/reports": () => jsonResponse(page([report])),
  "GET /api/v1/finance/allocations": () => jsonResponse(page([allocation])),
  "GET /api/v1/finance/journals": () => jsonResponse(page([journal])),
};

describe("Finance page", () => {
  it("shows the summary, closes with their checks and results, reports and allocations", async () => {
    mockApi(routes);
    renderApp("/finance");
    expect(await screen.findByLabelText("Finance summary")).toHaveTextContent("Last closed month2026-09");
    const closes = await screen.findByRole("table", { name: "Closes" });
    expect(closes).toHaveTextContent("2026-10 · Month ended ✓ Trial balance ✓ Reconciliation ✓ ECL provisions ✗");
    expect(closes).toHaveTextContent("USD: income $2,500.00, expense $1,000.00, net $1,500.00");
    expect(screen.getByLabelText("Close month")).toHaveValue("2026-10");
    const reports = screen.getByRole("table", { name: "Reports" });
    await userEvent.click(within(reports).getByRole("button", { name: "Rows of REG-0000001" }));
    expect(screen.getByRole("table", { name: "Report rows" })).toHaveTextContent("USDasset900000");
    expect(screen.getByRole("table", { name: "Allocations" })).toHaveTextContent("$1,000.00 across 2 departments by headcount");
    expect(screen.getByRole("table", { name: "Allocations" })).toHaveTextContent("Retail Operations (3): $750.00");
  });

  it("prepares and approves a close, extracts and submits a report, records a cost and posts an allocation", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/finance/closes": () => jsonResponse(prepared, 201),
      "POST /api/v1/finance/closes/cls-1/approve": () => jsonResponse({ ...prepared, status: "closed" }),
      "POST /api/v1/finance/reports": () => jsonResponse(report, 201),
      "POST /api/v1/finance/reports/reg-1/submit": () => jsonResponse({ ...report, status: "submitted", reference: "REGU-2026-09-0000001" }),
      "POST /api/v1/finance/expenses": () => jsonResponse({ entry_number: "JE-00000042", amount: 120_000, currency: "USD" }, 201),
      "POST /api/v1/finance/allocations": () => jsonResponse(allocation, 201),
      "POST /api/v1/finance/allocations/alc-1/post": () => jsonResponse({ ...allocation, status: "posted" }),
    });
    renderApp("/finance");
    await userEvent.click(within(await screen.findByRole("form", { name: "Prepare close" })).getByRole("button", { name: "Prepare close" }));
    await userEvent.click(screen.getByRole("button", { name: "Close CLS-0000002" }));
    const extract = screen.getByRole("form", { name: "Prepare report" });
    await userEvent.selectOptions(within(extract).getByLabelText("Report type"), "income_statement");
    await userEvent.click(within(extract).getByRole("button", { name: "Extract" }));
    await userEvent.click(screen.getByRole("button", { name: "Submit REG-0000001" }));
    const cost = screen.getByRole("form", { name: "Record expense" });
    await userEvent.type(within(cost).getByLabelText("Expense amount"), "1200");
    await userEvent.click(within(cost).getByRole("button", { name: "Record cost" }));
    expect(await within(cost).findByRole("status")).toHaveTextContent("JE-00000042 posted");
    await userEvent.click(within(screen.getByRole("form", { name: "Allocate costs" })).getByRole("button", { name: "Split USD costs" }));
    await userEvent.click(screen.getByRole("button", { name: "Post ALC-0000001" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(7));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/finance/closes"]).toEqual({ period: "2026-10" });
    expect(bodies["POST /api/v1/finance/reports"]).toEqual({ report_type: "income_statement", period: "2026-09" });
    expect(bodies["POST /api/v1/finance/expenses"]).toEqual({ currency: "USD", amount: 120_000, description: "Office rent" });
  });

  it("is read-only with only finance:read", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["finance:read"] }) });
    renderApp("/finance");
    expect(await screen.findByText("CLS-0000002")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Prepare close" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Record expense" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close CLS-0000002" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit REG-0000001" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download REG-0000001" })).toBeInTheDocument();
  });

  it("proposes and posts a manual journal", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/finance/journals": () => jsonResponse(journal, 201),
      "POST /api/v1/finance/journals/mj-1/approve": () => jsonResponse({ ...journal, status: "posted", entry_number: "JE-00000077" }),
    });
    renderApp("/finance");
    const table = await screen.findByRole("table", { name: "Journals" });
    await within(table).findByText("MJ-0000001");
    expect(table).toHaveTextContent("Dr FIN-SHARED-COSTS-USD $2,500.00Cr FIN-ACCRUALS-USD $2,500.00");
    const form = screen.getByRole("form", { name: "Propose journal" });
    await userEvent.type(within(form).getByLabelText("Debit account"), "fin-shared-costs-usd");
    await userEvent.type(within(form).getByLabelText("Credit account"), "FIN-ACCRUALS-USD");
    await userEvent.type(within(form).getByLabelText("Journal amount"), "2500");
    await userEvent.type(within(form).getByLabelText("Journal description"), "Accrual for legal fees");
    await userEvent.click(within(form).getByRole("button", { name: "Propose" }));
    expect(await within(form).findByRole("status")).toHaveTextContent("MJ-0000001 proposed");
    await userEvent.click(screen.getByRole("button", { name: "Post MJ-0000001" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(2));
    const proposed = api.requests.find((r) => r.path === "/api/v1/finance/journals" && r.method === "POST");
    expect(proposed?.body).toMatchObject({ currency: "USD", description: "Accrual for legal fees", lines: [
      { account_code: "FIN-SHARED-COSTS-USD", direction: "debit", amount: 250_000 },
      { account_code: "FIN-ACCRUALS-USD", direction: "credit", amount: 250_000 },
    ] });
  });
});
