import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { suggestedDate } from "@/features/lending/ServicingPanel";
import type { Instalment, Loan, ServicingRun } from "@/types/banking";

import { loan } from "./banking-fixtures";
import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const overdue: Loan = {
  ...loan,
  outstanding: 950_000,
  instalments_paid: 2,
  days_past_due: 44,
  arrears_amount: 61_662,
  arrears_bucket: "30-59",
  next_due_date: "2027-04-28",
};

const run: ServicingRun = {
  id: "run-1",
  run_number: 3,
  as_of: "2027-03-14",
  started_by_username: "manager",
  summary: {
    loans: 12,
    accrued: 14,
    collected: 11,
    missed: 3,
    repaid: 1,
    in_arrears: 2,
    arrears_amount: { USD: 61_662 },
    buckets: { current: 10, "30-59": 2 },
  },
  created_at: "2026-10-29T10:00:00Z",
};

const instalment = (number: number, status: Instalment["status"]): Instalment => ({
  number,
  due_date: `2027-0${number}-28`,
  principal: 25_000,
  interest: 5_831,
  amount: 30_831,
  status,
  paid_on: status === "paid" ? `2027-0${number}-28` : null,
});

function lendingRoutes() {
  return {
    ...healthyRoutes,
    "GET /api/v1/loans": () => jsonResponse(page([overdue])),
    "GET /api/v1/loans/servicing-runs": () => jsonResponse(page([run])),
    "POST /api/v1/loans/servicing-runs": () => jsonResponse({ ...run, id: "run-2", run_number: 4, as_of: "2027-04-14" }, 201),
    "GET /api/v1/loans/loan-1": () => jsonResponse(overdue),
    "GET /api/v1/loans/loan-1/schedule": () =>
      jsonResponse([instalment(1, "paid"), instalment(2, "paid"), instalment(3, "due"), instalment(4, "due"), instalment(5, "scheduled")]),
    "GET /api/v1/loans/loan-1/payoff-quote": () =>
      jsonResponse({ principal: 950_000, accrued_interest: 11_662, total: 961_662, as_of: "2027-03-14" }),
    "POST /api/v1/loans/loan-1/repayments": () => jsonResponse({ ...overdue, days_past_due: 0, arrears_amount: 0, arrears_bucket: "current" }),
    "POST /api/v1/loans/loan-1/payoff": () => jsonResponse({ ...overdue, status: "repaid", outstanding: 0 }),
    "GET /api/v1/workflow-executions": () => jsonResponse(page([])),
  };
}

describe("Loan servicing", () => {
  it("suggests servicing a month past the business date", () => {
    expect(suggestedDate("2027-01-28")).toBe("2027-02-28");
    expect(suggestedDate(null, new Date("2026-10-29T08:00:00Z"))).toBe("2026-10-29");
  });

  it("shows the business date and runs servicing to a chosen date", async () => {
    const api = mockApi(lendingRoutes());
    renderApp("/lending");

    await waitFor(() => expect(screen.getByTestId("business-date")).toHaveTextContent("2027-03-14"));
    const runs = screen.getByRole("table", { name: "Servicing runs" });
    const row = within(runs).getByText("#3").closest("tr") as HTMLElement;
    expect(within(row).getByText("$616.62")).toBeInTheDocument();
    expect(within(row).getByText("current: 10 · 30-59: 2")).toBeInTheDocument();
    const loanRow = within(screen.getByRole("table", { name: "Loans" })).getByText("LN-00000001").closest("tr") as HTMLElement;
    expect(within(loanRow).getByText("44 DPD")).toBeInTheDocument();
    expect(within(loanRow).getByText("$616.62 overdue")).toBeInTheDocument();

    const date = screen.getByLabelText("Service to");
    expect(date).toHaveValue("2027-04-14");
    await userEvent.click(screen.getByRole("button", { name: "Run servicing" }));

    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    const post = api.requests.find((r) => r.method === "POST");
    expect(post?.body).toEqual({ as_of: "2027-04-14" });
    expect(post?.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("repays arrears and pays a loan off from its schedule", async () => {
    const api = mockApi(lendingRoutes());
    renderApp("/lending");

    await userEvent.click(await screen.findByRole("button", { name: "Open LN-00000001" }));
    const dialog = await screen.findByRole("dialog", { name: "Loan LN-00000001" });
    const schedule = await within(dialog).findByRole("table", { name: "Repayment schedule" });
    expect(within(schedule).getAllByText("Due").filter((el) => el.tagName !== "TH")).toHaveLength(2);
    expect(within(dialog).getByText("44 days past due")).toBeInTheDocument();
    expect(within(dialog).getByText("2 of 36")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Repay arrears ($616.62)" }));
    await waitFor(() => expect(api.requests.some((r) => r.path.endsWith("/repayments"))).toBe(true));
    const repayment = api.requests.find((r) => r.path.endsWith("/repayments"));
    expect(repayment?.body).toEqual({});
    expect(repayment?.headers["Idempotency-Key"]).toBeTruthy();

    await userEvent.click(within(dialog).getByRole("button", { name: "Pay off early…" }));
    expect(await within(dialog).findByText("$9,616.62")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm payoff" }));
    await waitFor(() => expect(api.requests.some((r) => r.path.endsWith("/payoff"))).toBe(true));
    const payoff = api.requests.find((r) => r.path.endsWith("/payoff"));
    expect(payoff?.headers["Idempotency-Key"]).toBeTruthy();
    expect(payoff?.headers["Idempotency-Key"]).not.toBe(repayment?.headers["Idempotency-Key"]);
  });

  it("hides servicing and repayment actions without the permissions", async () => {
    const reader = { ...employeeUser, permissions: [...employeeUser.permissions, "loans:read" as const] };
    mockApi({ ...lendingRoutes(), ...authRoutes(reader) });
    renderApp("/lending");

    await userEvent.click(await screen.findByRole("button", { name: "Open LN-00000001" }));
    expect(screen.queryByRole("button", { name: "Run servicing" })).not.toBeInTheDocument();
    const dialog = await screen.findByRole("dialog", { name: "Loan LN-00000001" });
    await within(dialog).findByRole("table", { name: "Repayment schedule" });
    expect(within(dialog).queryByRole("button", { name: /Repay arrears/ })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Pay off early…" })).not.toBeInTheDocument();
  });
});
