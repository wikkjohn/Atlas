import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { CovenantTest, Facility, FacilityReview } from "@/types/commercial";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const facility = (overrides: Partial<Facility>): Facility => ({
  id: "fac-1",
  facility_number: "FAC-0000001",
  customer_number: "CUS-0000777",
  customer_name: "Harbour Tools Ltd",
  facility_type: "revolving",
  purpose: "Working capital",
  credit_limit: 25_000_000,
  currency: "GBP",
  annual_rate_bps: 750,
  term_months: 36,
  drawn: 5_000_000,
  available: 20_000_000,
  status: "active",
  frozen_reason: null,
  draw_block: null,
  needs_committee: false,
  approved: true,
  committee_approved: false,
  review_due_on: "2027-07-01",
  matures_on: "2029-07-01",
  covenants: [
    { kind: "max_leverage", threshold_centi: 350 },
    { kind: "min_dscr", threshold_centi: 125 },
  ],
  created_at: "2026-10-31T00:00:00Z",
  ...overrides,
});
const proposed = facility({ id: "fac-2", facility_number: "FAC-0000002", status: "proposed", approved: false, drawn: 0, available: 0, review_due_on: null });
const awaiting = facility({ id: "fac-3", facility_number: "FAC-0000003", status: "proposed", approved: true, needs_committee: true, credit_limit: 200_000_000 });
const breach: CovenantTest = {
  id: "test-1",
  facility_id: "fac-1",
  period_end: "2026-06-30",
  ebitda: 22_000_000,
  debt_service: 20_000_000,
  total_debt: 60_000_000,
  results: [
    { kind: "max_leverage", threshold_centi: 350, actual_centi: 272, passed: true },
    { kind: "min_dscr", threshold_centi: 125, actual_centi: 110, passed: false },
  ],
  breached: true,
  waived: false,
  created_at: "2026-10-31T00:00:00Z",
};
const review: FacilityReview = { id: "rev-1", review_number: "REV-0000001", facility_id: "fac-1", due_on: "2027-07-01", outcome: null, new_limit: null, decided_at: null };

const routes = {
  ...healthyRoutes,
  "GET /api/v1/commercial/summary/counts": () => jsonResponse({ proposed: 2, active: 1, frozen: 0, reviews_due: 1, open_reviews: 1 }),
  "GET /api/v1/commercial/facilities": () => jsonResponse(page([facility({}), proposed, awaiting])),
  "GET /api/v1/commercial/reviews": () => jsonResponse([review]),
  "GET /api/v1/commercial/facilities/fac-1/tests": () => jsonResponse([breach]),
};

describe("Commercial Lending page", () => {
  it("shows facilities, a facility's covenant tests and the reviews", async () => {
    mockApi(routes);
    renderApp("/commercial");
    const table = await screen.findByRole("table", { name: "Facilities" });
    const row = (await within(table).findByRole("button", { name: "Select FAC-0000001" })).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("drawn £50,000.00 · available £200,000.00");
    expect(within(table).getByText("awaiting committee")).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: "Select FAC-0000001" }));
    const detail = await screen.findByRole("region", { name: "Facility FAC-0000001" });
    expect(detail).toHaveTextContent("Leverage at most 3.50× · DSCR at least 1.25×");
    expect(await within(detail).findByText(/Min dscr 1.10× \(breached\)/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Reviews" })).toHaveTextContent("REV-0000001");
  });

  it("proposes, approves, draws, tests covenants, waives and renews", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/commercial/facilities": () => jsonResponse(proposed, 201),
      "POST /api/v1/commercial/facilities/fac-2/approve": () => jsonResponse({ ...proposed, status: "active" }),
      "POST /api/v1/commercial/facilities/fac-3/committee": () => jsonResponse({ ...awaiting, status: "active" }),
      "POST /api/v1/commercial/facilities/fac-1/draw": () => jsonResponse(facility({ drawn: 6_000_000 })),
      "POST /api/v1/commercial/facilities/fac-1/tests": () => jsonResponse(breach, 201),
      "POST /api/v1/commercial/tests/test-1/waive": () => jsonResponse(facility({})),
      "POST /api/v1/commercial/reviews/rev-1/decide": () => jsonResponse({ ...review, outcome: "renewed" }),
    });
    renderApp("/commercial");

    const form = await screen.findByRole("form", { name: "Propose a facility" });
    await userEvent.type(within(form).getByLabelText("Business customer"), "CUS-0000777");
    await userEvent.type(within(form).getByLabelText("Business account"), "GB000000000900");
    await userEvent.selectOptions(within(form).getByLabelText("Facility type"), "term_loan");
    await userEvent.type(within(form).getByLabelText("Credit limit"), "250000");
    await userEvent.click(within(form).getByRole("button", { name: "Propose" }));

    await userEvent.click(await screen.findByRole("button", { name: "Approve FAC-0000002" }));
    await userEvent.click(screen.getByRole("button", { name: "Committee approve FAC-0000003" }));

    await userEvent.click(screen.getByRole("button", { name: "Select FAC-0000001" }));
    const detail = await screen.findByRole("region", { name: "Facility FAC-0000001" });
    await userEvent.type(within(detail).getByLabelText("Amount"), "10000");
    await userEvent.click(within(detail).getByRole("button", { name: "Draw" }));
    const figures = within(detail).getByRole("form", { name: "Covenant figures" });
    await userEvent.type(within(figures).getByLabelText("Period end"), "2026-06-30");
    await userEvent.type(within(figures).getByLabelText("EBITDA"), "220000");
    await userEvent.type(within(figures).getByLabelText("Debt service"), "200000");
    await userEvent.type(within(figures).getByLabelText("Total debt"), "600000");
    await userEvent.click(within(figures).getByRole("button", { name: "Test covenants" }));
    await userEvent.click(await within(detail).findByRole("button", { name: "Waive 2026-06-30" }));
    await userEvent.click(screen.getByRole("button", { name: "Renew REV-0000001" }));

    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(7));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/commercial/facilities"]).toEqual({
      customer_number: "CUS-0000777",
      account_number: "GB000000000900",
      facility_type: "term_loan",
      credit_limit: 25_000_000,
      term_months: 36,
      purpose: "Working capital",
    });
    expect(bodies["POST /api/v1/commercial/facilities/fac-1/draw"]).toEqual({ amount: 1_000_000 });
    expect(bodies["POST /api/v1/commercial/facilities/fac-1/tests"]).toEqual({
      period_end: "2026-06-30",
      ebitda: 22_000_000,
      debt_service: 20_000_000,
      total_debt: 60_000_000,
    });
    expect(bodies["POST /api/v1/commercial/reviews/rev-1/decide"]).toEqual({ renew: true });
  });

  it("is read-only without the permissions", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["loans:read"] }) });
    renderApp("/commercial");
    await userEvent.click(await screen.findByRole("button", { name: "Select FAC-0000001" }));
    expect(await screen.findByRole("region", { name: "Facility FAC-0000001" })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Propose a facility" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Draw or repay" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Approve / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Waive / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Renew / })).not.toBeInTheDocument();
  });
});
