import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { IncomeDistribution, InvestmentOrder, Portfolio, Security, Valuation } from "@/types/wealth";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const securities: Security[] = [
  { id: "s-1", code: "AGB-GOVT-2031", name: "Synthetic Treasury 3.50% 2031", asset_class: "bond", currency: "USD", risk_level: 2, complex: false, price: 10_132, income_bps: 350 },
  { id: "s-2", code: "SN-AUTOCALL-28", name: "Atlas Autocall Note 2028", asset_class: "structured", currency: "USD", risk_level: 6, complex: true, price: 9_516, income_bps: 700 },
  { id: "s-3", code: "SN-DIGITAL-TRK", name: "Synthetic Digital Asset Tracker", asset_class: "structured", currency: "USD", risk_level: 7, complex: true, price: 5_689, income_bps: 0 },
];
const portfolio: Portfolio = {
  id: "p-1",
  portfolio_number: "INV-00000001",
  customer_number: "CUS-0000042",
  customer_name: "Synthetic Investor",
  account_number: "US000000000101",
  currency: "USD",
  status: "open",
  risk_profile: 4,
  created_at: "2026-10-31T09:00:00Z",
};
const valuation: Valuation = {
  portfolio_number: "INV-00000001",
  currency: "USD",
  as_of: "2026-11-01",
  holdings: [
    { security_code: "AGB-GOVT-2031", name: "Synthetic Treasury 3.50% 2031", asset_class: "bond", risk_level: 2, units: 60, price: 10_132, price_currency: "USD", value: 607_920, cost: 600_000, gain: 7_920 },
  ],
  value: 607_920,
  cost: 600_000,
  gain: 7_920,
  cash: 9_000_000,
};
const order = (overrides: Partial<InvestmentOrder>): InvestmentOrder => ({
  id: "o-1",
  order_number: "ORD-00000001",
  portfolio_number: "INV-00000001",
  security_code: "AGB-GOVT-2031",
  side: "buy",
  units: 100,
  price: 10_000,
  price_currency: "USD",
  amount: 1_000_000,
  fee: 2_500,
  currency: "USD",
  status: "executed",
  suitable: true,
  reasons: [],
  note: null,
  executed_on: "2026-10-31",
  created_at: "2026-10-31T10:00:00Z",
  ...overrides,
});
const unsuitable = order({
  id: "o-2",
  order_number: "ORD-00000002",
  security_code: "SN-AUTOCALL-28",
  units: 5,
  status: "awaiting_approval",
  suitable: false,
  reasons: [{ code: "risk_above_profile", message: "Risk level 6 is above the customer's profile of 4." }],
  executed_on: null,
});
const placed = order({ id: "o-3", order_number: "ORD-00000003", status: "placed", executed_on: null });
const distribution: IncomeDistribution = {
  id: "d-1",
  distribution_number: "DIS-0000001",
  security_code: "AGB-GOVT-2031",
  record_date: "2026-11-01",
  income_per_unit: 177,
  currency: "USD",
  holders: 3,
  created_at: "2026-11-01T08:00:00Z",
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/wealth/summary/counts": () => jsonResponse({ portfolios: 1, awaiting_approval: 1, placed: 1, executed: 1, profiles: 1, securities: 3 }),
  "GET /api/v1/wealth/securities": () => jsonResponse(securities),
  "GET /api/v1/wealth/portfolios": () => jsonResponse(page([portfolio])),
  "GET /api/v1/wealth/portfolios/INV-00000001/valuation": () => jsonResponse(valuation),
  "GET /api/v1/wealth/orders": () => jsonResponse(page([order({}), unsuitable, placed])),
  "GET /api/v1/wealth/distributions": () => jsonResponse(page([distribution])),
};

describe("Wealth page", () => {
  it("shows securities, portfolios with their valuation, orders and income", async () => {
    mockApi(routes);
    renderApp("/wealth");
    const table = await screen.findByRole("table", { name: "Securities" });
    expect((await within(table).findByText("SN-AUTOCALL-28")).closest("tr")).toHaveTextContent("Structured · complex");
    expect(within(table).getByText("AGB-GOVT-2031").closest("tr")).toHaveTextContent("3.50 % income");
    expect(await screen.findByText("INV-00000001")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Portfolios" })).toHaveTextContent("Synthetic Investor (CUS-0000042) · US000000000101 · USD · risk profile 4");
    await userEvent.click(screen.getByRole("button", { name: "View INV-00000001" }));
    const holdings = await screen.findByRole("table", { name: "Holdings" });
    expect(holdings).toHaveTextContent("60 units at $101.32 · risk 2");
    expect(screen.getByRole("region", { name: "Valuation of INV-00000001" })).toHaveTextContent("$6,079.20");
    const orders = screen.getByRole("table", { name: "Orders" });
    expect(within(orders).getByText("ORD-00000002").closest("tr")).toHaveTextContent("Risk level 6 is above the customer's profile of 4.");
    expect(screen.getByRole("table", { name: "Income distributions" })).toHaveTextContent("AGB-GOVT-2031 on 2026-11-01 · $1.77 a unit");
  });

  it("records a profile, opens a portfolio, places and decides orders, and pays income", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/wealth/profiles": () => jsonResponse({ id: "pr-1", objective: "growth", horizon_years: 15, knowledge: "informed", loss_capacity: "high", risk_profile: 6, assessed_on: "2026-11-01", expires_on: "2027-11-01" }, 201),
      "POST /api/v1/wealth/portfolios": () => jsonResponse({ ...portfolio, id: "p-2", portfolio_number: "INV-00000002" }, 201),
      "GET /api/v1/wealth/portfolios/INV-00000002/valuation": () => jsonResponse({ ...valuation, portfolio_number: "INV-00000002", holdings: [] }),
      "POST /api/v1/wealth/orders": () => jsonResponse(order({ id: "o-9", order_number: "ORD-00000009" }), 201),
      "POST /api/v1/wealth/orders/o-2/approve": () => jsonResponse({ ...unsuitable, status: "executed" }),
      "POST /api/v1/wealth/orders/o-3/release": () => jsonResponse({ ...placed, status: "executed" }),
      "POST /api/v1/wealth/distributions": () => jsonResponse(distribution, 201),
    });
    renderApp("/wealth");
    const profile = await screen.findByRole("form", { name: "Suitability assessment" });
    await userEvent.type(within(profile).getByLabelText("Customer number"), "cus-0000042");
    await userEvent.selectOptions(within(profile).getByLabelText("Objective"), "growth");
    await userEvent.clear(within(profile).getByLabelText("Horizon"));
    await userEvent.type(within(profile).getByLabelText("Horizon"), "15");
    await userEvent.selectOptions(within(profile).getByLabelText("Knowledge"), "informed");
    await userEvent.selectOptions(within(profile).getByLabelText("Capacity for loss"), "high");
    await userEvent.click(within(profile).getByRole("button", { name: "Record profile" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Risk profile 6, valid until 2027-11-01.");

    const open = screen.getByRole("form", { name: "Open a portfolio" });
    await userEvent.type(within(open).getByLabelText("Portfolio account"), "us000000000101");
    await userEvent.click(within(open).getByRole("button", { name: "Open portfolio" }));
    // The new portfolio is selected for the order form.
    const place = screen.getByRole("form", { name: "Place an order" });
    await waitFor(() => expect(within(place).getByLabelText("Order portfolio")).toHaveValue("INV-00000002"));
    await waitFor(() => expect(within(place).getByRole("option", { name: /AGB-GOVT-2031/ })).toBeInTheDocument());
    await userEvent.selectOptions(within(place).getByLabelText("Security"), "AGB-GOVT-2031");
    await userEvent.type(within(place).getByLabelText("Units"), "25");
    await userEvent.click(within(place).getByRole("button", { name: "Place order" }));

    await userEvent.click(screen.getByRole("button", { name: "Approve ORD-00000002" }));
    await userEvent.click(screen.getByRole("button", { name: "Release ORD-00000003" }));
    const income = screen.getByRole("form", { name: "Pay income" });
    // Only securities that pay income are offered.
    expect(within(income).queryByRole("option", { name: "SN-DIGITAL-TRK" })).not.toBeInTheDocument();
    await userEvent.selectOptions(within(income).getByLabelText("Income security"), "AGB-GOVT-2031");
    await userEvent.click(within(income).getByRole("button", { name: "Pay holders" }));

    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(6));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/wealth/profiles"]).toEqual({ customer_number: "CUS-0000042", objective: "growth", horizon_years: 15, knowledge: "informed", loss_capacity: "high" });
    expect(bodies["POST /api/v1/wealth/portfolios"]).toEqual({ account_number: "US000000000101" });
    expect(bodies["POST /api/v1/wealth/orders"]).toEqual({ portfolio_number: "INV-00000002", security_code: "AGB-GOVT-2031", side: "buy", units: 25 });
    expect(bodies["POST /api/v1/wealth/orders/o-2/approve"]).toEqual({ note: "Insistent client" });
    expect(bodies["POST /api/v1/wealth/distributions"]).toEqual({ security_code: "AGB-GOVT-2031" });
  });

  it("pages back to older orders beyond the newest 25", async () => {
    const api = mockApi({
      ...routes,
      "GET /api/v1/wealth/orders": (request) =>
        request.search.get("offset") === "25"
          ? jsonResponse(page([order({ id: "o-old", order_number: "ORD-00000099" })], 26, 25, 25))
          : jsonResponse(page([order({})], 26, 25, 0)),
    });
    renderApp("/wealth");
    const pages = await screen.findByRole("navigation", { name: "Order pages" });
    expect(pages).toHaveTextContent("1–25 of 26");
    await userEvent.click(within(pages).getByRole("button", { name: "Older" }));
    expect(await screen.findByText("ORD-00000099")).toBeInTheDocument();
    expect(api.requests.some((r) => r.path === "/api/v1/wealth/orders" && r.search.get("offset") === "25")).toBe(true);
  });

  it("is read-only without the wealth permissions", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["accounts:read"] }) });
    renderApp("/wealth");
    expect(await screen.findByText("INV-00000001")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Open a portfolio" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Place an order" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Pay income" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve ORD-00000002" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close INV-00000001" })).not.toBeInTheDocument();
  });
});
