import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { pendingCustomer, tellerUser, verifiedCustomer } from "./banking-fixtures";
import { authRoutes, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const base = {
  customers: 1203,
  generated: 1200,
  segments: { mass: 660, affluent: 180, senior: 144, sme: 96, student: 96, private: 24, unsegmented: 3 },
  countries: { US: 400, DE: 300 },
  risk: { low: 1000, medium: 180, high: 23 },
  products: { current: 1104, savings: 420, business_current: 96 },
  accounts_per_customer: { "1": 780, "2": 420 },
  history: { card: 21000, salary: 3200, housing: 3300, opening: 1620 },
};

function routes(customer = pendingCustomer) {
  return {
    ...healthyRoutes,
    "GET /api/v1/customers": () => jsonResponse(page([pendingCustomer, verifiedCustomer])),
    [`GET /api/v1/customers/${customer.id}`]: () => jsonResponse(customer),
    "GET /api/v1/accounts": () => jsonResponse(page([])),
    "GET /api/v1/account-requests": () => jsonResponse(page([])),
    "GET /api/v1/countries": () => jsonResponse(page([])),
    "GET /api/v1/customers/population/summary": () => jsonResponse(base),
    [`GET /api/v1/customers/${customer.id}/eligibility`]: () =>
      jsonResponse(
        customer.kyc_status === "verified"
          ? { eligible: true, reasons: [] }
          : { eligible: false, reasons: ["KYC is 'pending'; it must be verified."] },
      ),
  };
}

describe("Customers page", () => {
  it("lists customers with KYC and risk status", async () => {
    mockApi(routes());
    renderApp("/customers");

    const row = (await screen.findByText("Mara Lindqvist")).closest("tr") as HTMLElement;
    expect(within(row).getByText("KYC pending")).toBeInTheDocument();
    expect(within(row).getByText("Unrated")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Onboard customer" })).toBeInTheDocument();
  });

  it("offers reviewers only the KYC transitions the backend allows", async () => {
    const api = mockApi({
      ...routes(),
      "POST /api/v1/customers/cus-1/review": () =>
        jsonResponse({ ...pendingCustomer, kyc_status: "verified", risk_rating: "medium" }),
    });
    renderApp("/customers?customer=cus-1");

    const review = await screen.findByRole("region", { name: "KYC review" });
    expect(within(review).getByRole("button", { name: "Verify" })).toBeInTheDocument();
    expect(within(review).getByRole("button", { name: "Reject KYC" })).toBeInTheDocument();
    expect(within(review).queryByRole("button", { name: "Start review" })).not.toBeInTheDocument();

    await userEvent.selectOptions(within(review).getByLabelText("Risk rating"), "medium");
    await userEvent.click(within(review).getByRole("button", { name: "Verify" }));

    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toEqual({
      kyc_status: "verified",
      risk_rating: "medium",
      note: null,
    });
  });

  it("shows why a customer is not yet eligible and blocks the request", async () => {
    mockApi({ ...routes(), ...authRoutes(tellerUser) });
    renderApp("/customers?customer=cus-1");

    const panel = await screen.findByRole("region", { name: "Request an account" });
    expect(await within(panel).findByText("KYC is 'pending'; it must be verified.")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Submit for approval" })).toBeDisabled();
    // Tellers cannot make KYC decisions.
    expect(screen.queryByRole("region", { name: "KYC review" })).not.toBeInTheDocument();
  });

  it("submits an account request for an eligible customer", async () => {
    const api = mockApi({
      ...routes(verifiedCustomer),
      ...authRoutes(tellerUser),
      "POST /api/v1/account-requests": () => jsonResponse({}, 201),
    });
    renderApp("/customers?customer=cus-2");

    const panel = await screen.findByRole("region", { name: "Request an account" });
    const submit = within(panel).getByRole("button", { name: "Submit for approval" });
    await waitFor(() => expect(submit).toBeEnabled());
    await userEvent.click(submit);

    expect(await within(panel).findByRole("status")).toHaveTextContent("Another authorized employee must approve it");
    const post = api.requests.find((r) => r.method === "POST");
    expect(post?.body).toEqual({ customer_id: "cus-2", account_type: "current" });
    expect(post?.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("shows the customer base and generates customers (Phase 72)", async () => {
    const api = mockApi({
      ...routes(),
      "POST /api/v1/customers/population/generate": () =>
        jsonResponse({ created: 500, existing: 1200, accounts: 690, entries: 18000, seconds: 9.1 }),
    });
    renderApp("/customers");

    const panel = await screen.findByRole("region", { name: "Customer base" });
    expect(await within(panel).findByText("1,203 customers (1,200 generated)")).toBeInTheDocument();
    expect(within(panel).getByText(/Segments: Mass 660 · Affluent 180/)).toBeInTheDocument();
    expect(within(panel).getByLabelText("Accounts per customer")).toHaveTextContent("1: 780 · 2: 420");
    expect(within(panel).getByText(/Transaction history: Card 21,000/)).toBeInTheDocument();

    const count = within(panel).getByLabelText("Customers to generate");
    await userEvent.clear(count);
    await userEvent.type(count, "500");
    await userEvent.clear(within(panel).getByLabelText("Months of history"));
    await userEvent.type(within(panel).getByLabelText("Months of history"), "2");
    await userEvent.click(within(panel).getByRole("button", { name: "Generate customers" }));
    expect(await within(panel).findByRole("status")).toHaveTextContent("500 created (1,200 already there), 690 accounts, 18,000 entries in 9.1 s");
    expect(api.requests.find((r) => r.method === "POST")?.body).toEqual({ count: 500, seed: 2030, history_months: 2 });
  });

  it("does not offer the generator without customers:manage (Phase 72)", async () => {
    mockApi({ ...routes(), ...authRoutes({ ...tellerUser, permissions: tellerUser.permissions.filter((p) => p !== "customers:manage") }) });
    renderApp("/customers");

    const panel = await screen.findByRole("region", { name: "Customer base" });
    await within(panel).findByText(/1,203 customers/);
    expect(within(panel).queryByRole("form", { name: "Generate customers" })).not.toBeInTheDocument();
  });
});
