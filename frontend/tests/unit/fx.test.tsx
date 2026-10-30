import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const rates = [
  { currency: "EUR", rate_date: "2026-03-02", units_per_usd: "0.8618423036" },
  { currency: "JPY", rate_date: "2026-03-02", units_per_usd: "143.8916921849" },
  { currency: "USD", rate_date: "2026-03-02", units_per_usd: "1.0000000000" },
  { currency: "KWD", rate_date: "2026-03-02", units_per_usd: "0.3070000000" },
];

describe("Foreign Exchange page", () => {
  it("shows rates, quotes a conversion, and revalues the open positions", async () => {
    let unbooked = 25_000;
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/fx/rates": () => jsonResponse(rates),
      "POST /api/v1/fx/quote": () =>
        jsonResponse({
          sell_currency: "USD", sell_amount: 100_000, buy_currency: "EUR", buy_amount: 85_753,
          mid_rate: "0.861842303600", customer_rate: "0.857533092082", margin_bps: 50,
          rate_date: "2026-03-02", base_amount: 100_000,
        }),
      "GET /api/v1/fx/positions": () =>
        jsonResponse({
          as_of: "2026-03-02",
          positions: [
            { currency: "EUR", position: -4_287_665, units_per_usd: "0.8618423036", value_usd: -4_975_000 },
            { currency: "USD", position: 5_000_000, units_per_usd: "1.0000000000", value_usd: 5_000_000 },
          ],
          total_value_usd: 25_000,
          booked_usd: 25_000 - unbooked,
          unbooked_usd: unbooked,
        }),
      "GET /api/v1/fx/revaluations": () => jsonResponse(page([])),
      "GET /api/v1/fx/deals": () =>
        jsonResponse(page([{ id: "d1", deal_number: "FX-00000001", purpose: "payment", reference: "PAY-00000007 Invoice", rate_date: "2026-03-02", sell_currency: "USD", sell_amount: 5_000_000, buy_currency: "EUR", buy_amount: 4_287_665, mid_rate: "0.86", customer_rate: "0.857533092082", margin_bps: 50, created_at: "2026-03-02T10:00:00Z" }])),
      "POST /api/v1/fx/revaluations": () => {
        unbooked = 0;
        return jsonResponse({ id: "r1", run_number: 1, as_of: "2026-03-02", positions: [], total_value: 25_000, previously_booked: 0, posted: 25_000, journal_entry_id: "je", created_at: "2026-03-02T10:00:00Z" }, 201);
      },
    }); // prettier-ignore
    renderApp("/fx");

    const ratesRegion = await screen.findByRole("region", { name: "Exchange rates" });
    expect(await within(ratesRegion).findByText("143.892")).toBeInTheDocument();
    expect(within(ratesRegion).queryByText("KWD")).not.toBeInTheDocument(); // only the majors at first
    await userEvent.click(within(ratesRegion).getByRole("checkbox"));
    expect(within(ratesRegion).getByText("KWD")).toBeInTheDocument();

    const quote = screen.getByRole("region", { name: "Quote" });
    await userEvent.click(within(quote).getByRole("button", { name: "Quote" }));
    expect(await within(quote).findByRole("status")).toHaveTextContent("$1,000.00 buys €857.53 at 0.857533 (mid 0.861842, margin 0.5 %)");

    const positions = screen.getByRole("region", { name: "Currency positions" });
    expect(await within(positions).findByLabelText("Unbooked FX result")).toHaveTextContent("$250.00");
    expect(screen.getByText("FX-00000001")).toBeInTheDocument();
    await userEvent.click(within(positions).getByRole("button", { name: /^Revalue as of/ }));
    await waitFor(() => expect(within(positions).getByLabelText("Unbooked FX result")).toHaveTextContent("$0.00"));
    expect(api.requests.some((r) => r.method === "POST" && r.path === "/api/v1/fx/revaluations")).toBe(true);
  });
});
