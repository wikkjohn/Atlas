import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Counterparty, Deal, FxDesk, FxTrade, Liquidity } from "@/types/treasury";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const parties: Counterparty[] = [
  { id: "cp-1", code: "CP-NORTHGATE", name: "Northgate Commercial Bank (synthetic)", country_code: "GB", rating: "AA-", limit_usd: 250_000_000, exposure_usd: 1_250_000, investment_grade: true },
  { id: "cp-2", code: "CP-SAVANNA", name: "Savanna Continental Bank (synthetic)", country_code: "KE", rating: "BB+", limit_usd: 25_000_000, exposure_usd: 0, investment_grade: false },
];
const deal = (overrides: Partial<Deal>): Deal => ({
  id: "mm-1",
  deal_number: "MM-0000001",
  kind: "placement",
  counterparty_code: "CP-NORTHGATE",
  counterparty_name: "Northgate Commercial Bank (synthetic)",
  currency: "GBP",
  principal: 100_000_000,
  rate_bps: 450,
  day_basis: 365,
  value_date: "2026-10-01",
  maturity_date: "2026-10-31",
  interest: 369_863,
  status: "settled",
  created_at: "2026-10-01T00:00:00Z",
  ...overrides,
});
const booked = deal({ id: "mm-2", deal_number: "MM-0000002", status: "booked", maturity_date: "2027-01-29" });
const liquidity: Liquidity = {
  as_of: "2026-10-31",
  horizon_days: 30,
  run_off_bps: 1000,
  minimum_bps: 10_000,
  currencies: [
    { currency: "GBP", cash: 900_000_000, inflows: 100_369_863, deposits: 1_000_000_000, outflows: 0, liquid: 1_000_369_863, stressed_outflow: 100_000_000, coverage_bps: 100_036, below_minimum: false },
    { currency: "JPY", cash: 1_000, inflows: 0, deposits: 100_000, outflows: 0, liquid: 1_000, stressed_outflow: 10_000, coverage_bps: 1_000, below_minimum: true },
  ],
};
const desk: FxDesk = {
  as_of: "2026-10-31",
  total_value_usd: 0,
  positions: [{ currency: "EUR", position: 300_000_000, value_usd: 324_000_000, limit_usd: 1_000_000, utilisation_bps: 32_400, over_limit: true, excess_usd: 2_240_000 }],
};
const trade: FxTrade = {
  id: "fxt-1",
  trade_number: "FXT-0000001",
  counterparty_code: "CP-NORTHGATE",
  sell_currency: "EUR",
  sell_amount: 200_000_000,
  buy_currency: "USD",
  buy_amount: 216_000_000,
  mid_rate: "1.0800000000",
  trade_date: "2026-10-31",
  status: "booked",
  created_at: "2026-10-31T00:00:00Z",
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/treasury/summary/counts": () => jsonResponse({ booked: 1, placements: 1, borrowings: 0, fx_trades_booked: 1 }),
  "GET /api/v1/treasury/counterparties": () => jsonResponse(parties),
  "GET /api/v1/treasury/deals": () => jsonResponse(page([deal({}), booked])),
  "GET /api/v1/treasury/liquidity": () => jsonResponse(liquidity),
  "GET /api/v1/treasury/fx-desk": () => jsonResponse(desk),
  "GET /api/v1/treasury/fx-trades": () => jsonResponse(page([trade])),
};

describe("Treasury page", () => {
  it("shows deals, liquidity, the FX desk and counterparties", async () => {
    mockApi(routes);
    renderApp("/treasury");
    const deals = await screen.findByRole("table", { name: "Deals" });
    const row = (await within(deals).findByText("MM-0000001")).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("Placement · CP-NORTHGATE · 4.50 % ACT/365 · matures 2026-10-31");
    expect(row).toHaveTextContent("£1,000,000.00");
    const liquidityTable = screen.getByRole("table", { name: "Liquidity" });
    expect(within(liquidityTable).getByText("JPY").closest("tr")).toHaveTextContent("10 %");
    const positions = screen.getByRole("table", { name: "Positions" });
    expect(within(positions).getByText("EUR").closest("tr")).toHaveTextContent("over limit");
    const counterparties = screen.getByRole("table", { name: "Counterparties" });
    expect(within(counterparties).getByText("CP-SAVANNA").closest("tr")).toHaveTextContent("(borrowing only)");
  });

  it("books, confirms and settles deals and squares a position", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/treasury/deals": () => jsonResponse(deal({ id: "mm-9", deal_number: "MM-0000009", status: "booked" }), 201),
      "POST /api/v1/treasury/deals/mm-2/confirm": () => jsonResponse({ ...booked, status: "settled" }),
      "POST /api/v1/treasury/deals/mm-1/mature": () => jsonResponse(deal({ status: "matured" })),
      "POST /api/v1/treasury/fx-trades": () => jsonResponse({ ...trade, id: "fxt-2", trade_number: "FXT-0000002" }, 201),
      "POST /api/v1/treasury/fx-trades/fxt-1/confirm": () => jsonResponse({ ...trade, status: "settled" }),
    });
    renderApp("/treasury");
    const form = await screen.findByRole("form", { name: "Book a deal" });
    await userEvent.selectOptions(within(form).getByLabelText("Kind"), "borrowing");
    await waitFor(() => expect(within(form).getByRole("option", { name: "CP-SAVANNA (BB+)" })).toBeInTheDocument());
    await userEvent.selectOptions(within(form).getByLabelText("Counterparty"), "CP-SAVANNA");
    await userEvent.type(within(form).getByLabelText("Currency"), "jpy");
    await userEvent.type(within(form).getByLabelText("Principal"), "50000000");
    await userEvent.type(within(form).getByLabelText("Rate"), "0.25");
    await userEvent.clear(within(form).getByLabelText("Tenor"));
    await userEvent.type(within(form).getByLabelText("Tenor"), "90");
    await userEvent.click(within(form).getByRole("button", { name: "Book" }));

    await userEvent.click(screen.getByRole("button", { name: "Confirm MM-0000002" }));
    await userEvent.click(screen.getByRole("button", { name: "Mature MM-0000001" }));

    const square = screen.getByRole("form", { name: "Square a position" });
    await userEvent.selectOptions(within(square).getByLabelText("Trade counterparty"), "CP-NORTHGATE");
    await userEvent.type(within(square).getByLabelText("Sell currency"), "EUR");
    await userEvent.type(within(square).getByLabelText("Amount sold"), "2000000");
    await userEvent.click(within(square).getByRole("button", { name: "Book trade" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm FXT-0000001" }));

    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(5));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/treasury/deals"]).toEqual({
      kind: "borrowing",
      counterparty_code: "CP-SAVANNA",
      currency: "JPY",
      principal: 50_000_000, // yen have no minor unit
      rate_bps: 25,
      tenor_days: 90,
    });
    expect(bodies["POST /api/v1/treasury/fx-trades"]).toEqual({ counterparty_code: "CP-NORTHGATE", sell_currency: "EUR", buy_currency: "USD", sell_amount: 200_000_000 });
  });

  it("pages back to older deals and FX trades beyond the newest 25 (PR #30 review)", async () => {
    const api = mockApi({
      ...routes,
      "GET /api/v1/treasury/deals": (request) =>
        request.search.get("offset") === "25"
          ? jsonResponse(page([deal({ id: "mm-old", deal_number: "MM-0000099" })], 26, 25, 25))
          : jsonResponse(page([deal({}), booked], 26, 25, 0)),
      "GET /api/v1/treasury/fx-trades": (request) =>
        request.search.get("offset") === "25"
          ? jsonResponse(page([{ ...trade, id: "fxt-old", trade_number: "FXT-0000099" }], 27, 25, 25))
          : jsonResponse(page([trade], 27, 25, 0)),
    });
    renderApp("/treasury");
    const dealPages = await screen.findByRole("navigation", { name: "Deal pages" });
    expect(dealPages).toHaveTextContent("1–25 of 26");
    await userEvent.click(within(dealPages).getByRole("button", { name: "Older" }));
    expect(await screen.findByText("MM-0000099")).toBeInTheDocument();
    const tradePages = screen.getByRole("navigation", { name: "FX trade pages" });
    await userEvent.click(within(tradePages).getByRole("button", { name: "Older" }));
    expect(await screen.findByText("FXT-0000099")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "FX trade pages" })).toHaveTextContent("26–27 of 27");
    expect(api.requests.filter((r) => r.search.get("offset") === "25")).toHaveLength(2);
  });

  it("is read-only without the treasury permissions", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["payments:read"] }) });
    renderApp("/treasury");
    expect(await screen.findByText("MM-0000002")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Book a deal" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Square a position" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Counterparty limit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Confirm / })).not.toBeInTheDocument();
  });
});
