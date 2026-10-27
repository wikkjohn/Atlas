import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { account, cleanReport, request, tellerUser } from "./banking-fixtures";
import { adminUser, authRoutes, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const statement = page([
  {
    entry_id: "je-1",
    entry_number: "JE-00000001",
    posted_at: "2026-10-27T10:00:00Z",
    description: "Cash deposit",
    source: "deposit",
    direction: "credit",
    amount: 123_456,
    memo: null,
  },
]);

function routes() {
  return {
    ...healthyRoutes,
    "GET /api/v1/accounts": () => jsonResponse(page([account])),
    "GET /api/v1/accounts/acc-1": () => jsonResponse(account),
    "GET /api/v1/accounts/acc-1/transactions": () => jsonResponse(statement),
  };
}

describe("Accounts page", () => {
  it("shows the ledger-derived balance and transactions", async () => {
    mockApi(routes());
    renderApp("/accounts?account=acc-1");

    const dialog = await screen.findByRole("dialog", { name: "Account" });
    expect(await within(dialog).findByLabelText("Balance")).toHaveTextContent("$1,234.56");
    const history = within(dialog).getByRole("region", { name: "Transactions" });
    expect(await within(history).findByText("+$1,234.56")).toBeInTheDocument();
  });

  it("reuses the idempotency key when a failed deposit is retried", async () => {
    let attempt = 0;
    const api = mockApi({
      ...routes(),
      ...authRoutes(tellerUser),
      "POST /api/v1/accounts/acc-1/deposits": () => {
        attempt += 1;
        if (attempt === 1) throw new TypeError("Failed to fetch");
        return jsonResponse(
          { account, journal_entry_id: "je-2", entry_number: "JE-00000002", replayed: false },
          201,
        );
      },
    });
    renderApp("/accounts?account=acc-1");

    const form = await screen.findByRole("form", { name: "Deposit" });
    await userEvent.type(within(form).getByLabelText("Deposit (USD)"), "25.50");
    await userEvent.click(within(form).getByRole("button", { name: "Deposit" }));
    await within(form).findByRole("alert");
    await userEvent.click(within(form).getByRole("button", { name: "Deposit" }));
    await within(form).findByText(/Posted JE-00000002/);

    const posts = api.requests.filter((r) => r.method === "POST");
    expect(posts).toHaveLength(2);
    expect(posts[0].body).toEqual({ amount: 2550, memo: null });
    expect(posts[1].headers["Idempotency-Key"]).toBe(posts[0].headers["Idempotency-Key"]);
  });

  it("marks your own requests as needing another approver", async () => {
    const managerUser = { ...adminUser, id: "user-teller" };
    const api = mockApi({
      ...healthyRoutes,
      ...authRoutes(managerUser),
      "GET /api/v1/accounts": () => jsonResponse(page([])),
      "GET /api/v1/account-requests": () =>
        jsonResponse(page([request({}), request({ id: "req-2", requested_by: "someone-else", customer_name: "Ava Chen" })])),
      "POST /api/v1/account-requests/req-2/approve": () => jsonResponse({}),
    });
    renderApp("/accounts?tab=requests");

    const own = (await screen.findByText("Kenji Watanabe")).closest("tr") as HTMLElement;
    expect(within(own).getByText("Needs another approver")).toBeInTheDocument();
    expect(within(own).queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();

    const other = screen.getByText("Ava Chen").closest("tr") as HTMLElement;
    await userEvent.click(within(other).getByRole("button", { name: /Approve/ }));
    await waitFor(() =>
      expect(api.requests.some((r) => r.path === "/api/v1/account-requests/req-2/approve")).toBe(true),
    );
  });

  it("runs reconciliation and lists the checks", async () => {
    mockApi({
      ...routes(),
      "GET /api/v1/ledger/accounts": () => jsonResponse(page([])),
      "GET /api/v1/ledger/journal-entries": () => jsonResponse(page([])),
      "POST /api/v1/ledger/reconciliation": () => jsonResponse(cleanReport),
    });
    renderApp("/accounts?tab=ledger");

    await userEvent.click(await screen.findByRole("button", { name: "Run reconciliation" }));

    const section = screen.getByRole("region", { name: "Reconciliation" });
    expect(await within(section).findByText(/All checks passed/)).toBeInTheDocument();
    expect(within(section).getByText("Every entry balances")).toBeInTheDocument();
  });

  it("hides the general ledger from roles without ledger access", async () => {
    mockApi({ ...routes(), ...authRoutes(tellerUser) });
    renderApp("/accounts");

    expect(await screen.findByRole("tab", { name: "Opening requests" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "General ledger" })).not.toBeInTheDocument();
  });
});
