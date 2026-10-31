import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { TradeDemand, TradeInstrument } from "@/types/trade";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const instrument = (overrides: Partial<TradeInstrument>): TradeInstrument => ({
  id: "lc-1",
  instrument_number: "LC-0000001",
  kind: "letter_of_credit",
  customer_number: "CUS-0000777",
  customer_name: "Harbour Tools Ltd",
  beneficiary_name: "Saigon Coffee Exporters",
  beneficiary_country: "VN",
  purpose: "Green coffee",
  amount: 5_000_000,
  currency: "GBP",
  margin_bps: 2000,
  margin: 1_000_000,
  drawn: 0,
  expires_on: "2027-02-28",
  status: "issued",
  needs_committee: false,
  approved: true,
  committee_approved: false,
  screening_list: "synthetic-un-v1",
  created_at: "2026-10-31T00:00:00Z",
  ...overrides,
});
const requested = instrument({ id: "bg-2", instrument_number: "BG-0000002", kind: "guarantee", status: "requested", approved: false, margin: 0, margin_bps: 1000 });
const awaiting = instrument({ id: "lc-3", instrument_number: "LC-0000003", status: "requested", needs_committee: true, amount: 200_000_000, margin: 0 });
const demand: TradeDemand = {
  id: "dmd-1",
  demand_number: "DMD-0000001",
  instrument_id: "lc-1",
  amount: 2_000_000,
  presented_on: "2026-10-30",
  discrepancies: ["late_shipment"],
  status: "pending",
  decision_note: null,
  decided_at: null,
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/trade/summary/counts": () => jsonResponse({ requested: 2, issued: 1, pending_demands: 1, paid: 0, expired: 0 }),
  "GET /api/v1/trade/instruments": () => jsonResponse(page([instrument({}), requested, awaiting])),
  "GET /api/v1/trade/instruments/lc-1/demands": () => jsonResponse([demand]),
};

describe("Trade finance page", () => {
  it("lists instruments with their approval state and summary", async () => {
    mockApi(routes);
    renderApp("/trade");
    const table = await screen.findByRole("table", { name: "Instruments" });
    const row = (await within(table).findByText("LC-0000001")).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("Harbour Tools Ltd → Saigon Coffee Exporters (VN) · Green coffee · expires 2027-02-28");
    expect(row).toHaveTextContent("£50,000.00");
    expect(within(table).getByText("LC-0000003").closest("tr")).toHaveTextContent("awaiting committee");
    const summary = (await screen.findByText("Demands to check")).closest("div") as HTMLElement;
    expect(within(summary).getByText("1")).toBeInTheDocument();
  });

  it("requests, approves, presents documents and pays a discrepant presentation", async () => {
    const api = mockApi({
      ...routes,
      "GET /api/v1/accounts": () => jsonResponse(page([{ account_number: "JP000000000900", currency: "JPY" }])),
      "POST /api/v1/trade/instruments": () => jsonResponse(instrument({ id: "lc-9", instrument_number: "LC-0000009", status: "requested" }), 201),
      "POST /api/v1/trade/instruments/bg-2/approve": () => jsonResponse({ ...requested, status: "issued", approved: true }),
      "POST /api/v1/trade/instruments/lc-3/committee": () => jsonResponse({ ...awaiting, status: "issued" }),
      "POST /api/v1/trade/instruments/lc-1/demands": () => jsonResponse({ ...demand, id: "dmd-2", demand_number: "DMD-0000002" }, 201),
      "POST /api/v1/trade/demands/dmd-1/pay": () => jsonResponse({ ...demand, status: "paid" }),
    });
    renderApp("/trade");

    const form = await screen.findByRole("form", { name: "Request an instrument" });
    await userEvent.type(within(form).getByLabelText("Business customer"), "CUS-0000777");
    await userEvent.type(within(form).getByLabelText("Business account"), "JP000000000900");
    await userEvent.type(within(form).getByLabelText("Beneficiary"), "Saigon Coffee Exporters");
    await userEvent.type(within(form).getByLabelText("Beneficiary country"), "vn");
    await userEvent.type(within(form).getByLabelText("Amount"), "5000000");
    await userEvent.type(within(form).getByLabelText("Expires on"), "2027-02-28");
    await userEvent.click(within(form).getByRole("button", { name: "Request" }));

    await userEvent.click(await screen.findByRole("button", { name: "Approve BG-0000002" }));
    await userEvent.click(screen.getByRole("button", { name: "Committee approve LC-0000003" }));
    expect(screen.queryByRole("button", { name: "Approve LC-0000003" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Select LC-0000001" }));
    const detail = await screen.findByRole("region", { name: "Instrument LC-0000001" });
    expect(detail).toHaveTextContent("Margin held £10,000.00 (20 %)");
    const present = within(detail).getByRole("form", { name: "Present documents" });
    await userEvent.type(within(present).getByLabelText("Demand amount"), "20000");
    await userEvent.type(within(present).getByLabelText("Presented on"), "2026-10-30");
    await userEvent.selectOptions(within(present).getByLabelText("Discrepancy"), "missing_document");
    await userEvent.click(within(present).getByRole("button", { name: "Present documents" }));
    const demands = within(detail).getByRole("table", { name: "Demands" });
    expect(await within(demands).findByText(/Late shipment/)).toBeInTheDocument();
    const pay = within(demands).getByRole("button", { name: "Pay DMD-0000001" });
    expect(pay).toHaveTextContent("Pay (waived)");
    await userEvent.click(pay);

    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(5));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/trade/instruments"]).toEqual({
      kind: "letter_of_credit",
      customer_number: "CUS-0000777",
      account_number: "JP000000000900",
      beneficiary_name: "Saigon Coffee Exporters",
      beneficiary_country: "VN",
      amount: 5_000_000, // JPY has no minor units
      expires_on: "2027-02-28",
      purpose: "Trade",
    });
    expect(bodies["POST /api/v1/trade/instruments/lc-1/demands"]).toEqual({ amount: 2_000_000, presented_on: "2026-10-30", discrepancies: ["missing_document"] });
  });

  it("pages back to older instruments beyond the first 25 (PR #28 review)", async () => {
    const api = mockApi({
      ...routes,
      "GET /api/v1/trade/instruments": (request) =>
        request.search.get("offset") === "25"
          ? jsonResponse(page([instrument({ id: "lc-old", instrument_number: "LC-0000099" })], 26, 25, 25))
          : jsonResponse(page([instrument({}), requested, awaiting], 26, 25, 0)),
    });
    renderApp("/trade");
    const pages = await screen.findByRole("navigation", { name: "Instrument pages" });
    expect(pages).toHaveTextContent("1–25 of 26");
    expect(within(pages).getByRole("button", { name: "Newer" })).toBeDisabled();
    await userEvent.click(within(pages).getByRole("button", { name: "Older" }));
    expect(await screen.findByRole("button", { name: "Select LC-0000099" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Instrument pages" })).toHaveTextContent("26–26 of 26");
    expect(api.requests.some((r) => r.path === "/api/v1/trade/instruments" && r.search.get("offset") === "25")).toBe(true);
  });

  it("is read-only without the permissions", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["loans:read"] }) });
    renderApp("/trade");
    await userEvent.click(await screen.findByRole("button", { name: "Select LC-0000001" }));
    expect(await screen.findByText("DMD-0000001")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Request an instrument" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Present documents" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Approve / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Pay / })).not.toBeInTheDocument();
  });
});
