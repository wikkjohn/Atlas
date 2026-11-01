import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { CreditRating, Obligor, ProvisionRun } from "@/types/risk";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const obligor: Obligor = {
  customer_number: "CUS-0000042",
  name: "Synthetic Customer",
  grade: 6,
  pd_bps: 100,
  limit_usd: 5_000,
  limit_source: "set",
  exposure_usd: 6_200,
  excess_usd: 1_200,
  exposures: [{ type: "loan", reference: "LN-0000001", currency: "USD", ead: 620_000, days_past_due: 44 }],
};
const pending: CreditRating = {
  id: "rat-1",
  rating_number: "RAT-0000001",
  customer_number: "CUS-0000043",
  customer_name: "Another Customer",
  grade: 8,
  suggested_grade: 6,
  pd_bps: 500,
  factors: {},
  rationale: "Sector under stress",
  status: "pending",
  rated_on: "2026-11-01",
  expires_on: "2027-11-01",
};
const run: ProvisionRun = {
  id: "prv-1",
  run_number: "PRV-0000001",
  as_of: "2026-11-01",
  status: "calculated",
  exposures: 12,
  totals: { USD: { stage_1: 10_000, stage_2: 20_000, stage_3: 0, ecl: 30_000, ead: 9_000_000, previous: 0, change: 30_000 } },
  note: null,
  created_at: "2026-11-01T09:00:00Z",
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/risk/summary/counts": () => jsonResponse({ ratings_pending: 1, ratings: 4, runs_to_approve: 1, last_posted_run: null, last_posted_as_of: null }),
  "GET /api/v1/risk/obligors/CUS-0000042": () => jsonResponse(obligor),
  "GET /api/v1/risk/breaches": () => jsonResponse([{ ...obligor, exposures: undefined }]),
  "GET /api/v1/risk/ratings": () => jsonResponse(page([pending])),
  "GET /api/v1/risk/provisions": () => jsonResponse(page([run])),
  "GET /api/v1/risk/provisions/prv-1/lines": () =>
    jsonResponse(page([{ exposure_type: "loan", reference: "LN-0000001", currency: "USD", ead: 620_000, days_past_due: 44, grade: 6, stage: 2, pd_bps: 200, lgd_bps: 4_500, ecl: 5_580 }])),
};

describe("Risk page", () => {
  it("shows the summary, breaches, ratings and provision runs", async () => {
    mockApi(routes);
    renderApp("/risk");
    expect(await screen.findByLabelText("Risk summary")).toHaveTextContent("Ratings to approve1");
    expect(await screen.findByRole("table", { name: "Limit breaches" })).toHaveTextContent("Synthetic Customer · grade 6 · limit $5,000.00");
    expect(await screen.findByRole("table", { name: "Ratings" })).toHaveTextContent("Another Customer (CUS-0000043) · grade 8 (model 6) · Sector under stress");
    const runs = await screen.findByRole("table", { name: "Provision runs" });
    expect(runs).toHaveTextContent("USD: ECL $300.00");
    await userEvent.click(within(runs).getByRole("button", { name: "Lines of PRV-0000001" }));
    expect(await screen.findByRole("table", { name: "Provision lines" })).toHaveTextContent("loan · stage 2 · grade 6 · PD 2.00 % · LGD 45.00 % · 44 days past due");
  });

  it("looks up an obligor, rates it, sets its limit, approves a rating and posts a run", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/risk/ratings": () => jsonResponse({ ...pending, id: "rat-2", rating_number: "RAT-0000002", customer_number: "CUS-0000042", grade: 7 }, 201),
      "PUT /api/v1/risk/limits": () => jsonResponse(obligor),
      "POST /api/v1/risk/ratings/rat-1/approve": () => jsonResponse({ ...pending, status: "approved" }),
      "POST /api/v1/risk/provisions/prv-1/post": () => jsonResponse({ ...run, status: "posted" }),
    });
    renderApp("/risk");
    await userEvent.type(await screen.findByLabelText("Customer number"), "cus-0000042");
    await userEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(await screen.findByLabelText("Obligor grade")).toHaveTextContent("Grade 6 (PD 1.00 %) · limit $5,000.00 (set) · exposure $6,200.00 · $1,200.00 over the limit");
    const rate = screen.getByRole("form", { name: "Rate obligor" });
    await userEvent.selectOptions(within(rate).getByLabelText("Grade"), "7");
    await userEvent.type(within(rate).getByLabelText("Rationale"), "Weak trading outlook");
    await userEvent.click(within(rate).getByRole("button", { name: "Rate" }));
    expect(await within(rate).findByRole("status")).toHaveTextContent("RAT-0000002: grade 7, pending");
    const limit = screen.getByRole("form", { name: "Set limit" });
    await userEvent.clear(within(limit).getByLabelText("Limit in US dollars"));
    await userEvent.type(within(limit).getByLabelText("Limit in US dollars"), "8000");
    await userEvent.click(within(limit).getByRole("button", { name: "Set limit" }));
    await userEvent.click(screen.getByRole("button", { name: "Approve RAT-0000001" }));
    await userEvent.click(screen.getByRole("button", { name: "Post PRV-0000001" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(4));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/risk/ratings"]).toEqual({ customer_number: "CUS-0000042", grade: 7, rationale: "Weak trading outlook" });
    expect(bodies["PUT /api/v1/risk/limits"]).toEqual({ customer_number: "CUS-0000042", limit_usd: 8000, note: "Set on the risk page" });
  });

  it("is read-only with only risk:read", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["risk:read"] }) });
    renderApp("/risk");
    expect(await screen.findByText("RAT-0000001")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Customer number"), "CUS-0000042");
    await userEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(await screen.findByLabelText("Obligor grade")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Rate obligor" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Set limit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve RAT-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Calculate ECL" })).not.toBeInTheDocument();
  });
});
