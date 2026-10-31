import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Card, CardAuthorization, CardDispute } from "@/types/cards";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const active: Card = {
  id: "card-1",
  card_number: "9999 •••• •••• 4242",
  last4: "4242",
  product_code: "debit-standard",
  account_id: "acc-1",
  account_number: "GB000000000101",
  currency: "GBP",
  daily_limit: 120_000,
  expires_on: "2030-10-31T00:00:00Z",
  status: "active",
  blocked_reason: null,
  issued_at: "2026-10-31T00:00:00Z",
};
const blocked: Card = { ...active, id: "card-2", card_number: "9999 •••• •••• 1881", last4: "1881", status: "blocked", blocked_reason: "fraud_suspected" };
const declined: CardAuthorization = {
  id: "auth-1",
  auth_code: "AUTH-00000007",
  card_id: "card-2",
  card_last4: "1881",
  merchant_name: "Lucky Spins",
  merchant_category: "7995",
  merchant_country: "MT",
  amount: 5_000,
  currency: "GBP",
  status: "declined",
  decline_reason: "fraud_suspected",
  fraud_score: 70,
  fraud_signals: ["foreign_merchant", "high_risk_category"],
  created_at: "2026-10-31T10:00:00Z",
};
const dispute: CardDispute = {
  id: "dsp-1",
  dispute_number: "DSP-0000003",
  auth_code: "AUTH-00000005",
  reason: "not_received",
  amount: 40_000,
  currency: "GBP",
  status: "open",
  opened_at: "2026-10-31T11:00:00Z",
  decided_at: null,
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/cards/summary/counts": () => jsonResponse({ active_cards: 1, blocked_cards: 1, authorizations: 6, declined: 2, open_disputes: 1 }),
  "GET /api/v1/cards": () => jsonResponse(page([active, blocked])),
  "GET /api/v1/cards/authorizations/list": () => jsonResponse(page([declined])),
  "GET /api/v1/cards/disputes/list": () => jsonResponse(page([dispute])),
};

describe("Cards page", () => {
  it("shows cards, purchases with their fraud signals and disputes", async () => {
    mockApi(routes);
    renderApp("/cards");

    const cards = await screen.findByRole("table", { name: "Cards" });
    expect(await within(cards).findByText("9999 •••• •••• 4242")).toBeInTheDocument();
    expect(within(cards).getByText(/fraud suspected/)).toBeInTheDocument();
    const summary = (await screen.findByText("Open disputes")).closest("div") as HTMLElement;
    expect(within(summary).getByText("1")).toBeInTheDocument();
    const purchases = screen.getByRole("table", { name: "Purchases" });
    expect(await within(purchases).findByText("AUTH-00000007")).toBeInTheDocument();
    expect(within(purchases).getByText("score 70")).toBeInTheDocument();
    expect(await within(screen.getByRole("table", { name: "Disputes" })).findByText("DSP-0000003")).toBeInTheDocument();
  });

  it("issues a card, pays at the terminal, releases a block and charges back a dispute", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/cards": () => jsonResponse({ ...active, id: "card-3" }, 201),
      "POST /api/v1/cards/card-1/authorizations": () => jsonResponse({ ...declined, card_id: "card-1", card_last4: "4242" }, 201),
      "POST /api/v1/cards/card-2/unblock": () => jsonResponse({ ...blocked, status: "active", blocked_reason: null }),
      "POST /api/v1/cards/disputes/dsp-1/decide": () => jsonResponse({ ...dispute, status: "refunded" }),
    });
    renderApp("/cards");

    const issue = await screen.findByRole("form", { name: "Issue a card" });
    await userEvent.type(within(issue).getByLabelText("Account"), "GB000000000101");
    await userEvent.selectOptions(within(issue).getByLabelText("Product"), "debit-premium");
    await userEvent.click(within(issue).getByRole("button", { name: "Issue card" }));

    const terminal = await screen.findByRole("form", { name: "Merchant terminal" });
    await userEvent.clear(within(terminal).getByLabelText("Merchant"));
    await userEvent.type(within(terminal).getByLabelText("Merchant"), "Lucky Spins");
    await userEvent.selectOptions(within(terminal).getByLabelText("Category"), "7995");
    await userEvent.clear(within(terminal).getByLabelText("Merchant country"));
    await userEvent.type(within(terminal).getByLabelText("Merchant country"), "mt");
    await userEvent.clear(within(terminal).getByLabelText("Amount"));
    await userEvent.type(within(terminal).getByLabelText("Amount"), "50.00");
    await userEvent.click(within(terminal).getByRole("button", { name: "Pay" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "AUTH-00000007: declined (fraud suspected) · fraud score 70 · foreign_merchant, high_risk_category",
    );

    await userEvent.click(screen.getByRole("button", { name: "Release card 1881" }));
    await userEvent.click(screen.getByRole("button", { name: "Charge back DSP-0000003" }));

    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(4));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/cards"]).toEqual({ account_number: "GB000000000101", product_code: "debit-premium" });
    expect(bodies["POST /api/v1/cards/card-1/authorizations"]).toEqual({
      merchant_name: "Lucky Spins",
      merchant_category: "7995",
      merchant_country: "MT",
      amount: 5_000,
    });
    expect(bodies["POST /api/v1/cards/disputes/dsp-1/decide"]).toEqual({ refund: true });
  });

  it("hides issuing, the terminal and decisions without the permissions", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["accounts:read"] }) });
    renderApp("/cards");
    expect(await screen.findByText("9999 •••• •••• 4242")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Issue a card" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Merchant terminal" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Release card/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Charge back/ })).not.toBeInTheDocument();
  });
});
