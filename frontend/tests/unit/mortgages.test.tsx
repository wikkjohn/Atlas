import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { MortgageOffer, MortgageProduct, Property, Quote } from "@/types/mortgages";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const products: MortgageProduct[] = [
  { product_code: "home-75", name: "ATLAS Home 75", max_ltv_bps: 7500, annual_rate_bps: 449, max_term_years: 35, min_loan_usd: 25000, max_loan_usd: 1000000 },
  { product_code: "home-90", name: "ATLAS Home 90", max_ltv_bps: 9000, annual_rate_bps: 579, max_term_years: 35, min_loan_usd: 25000, max_loan_usd: 750000 },
];
const property: Property = {
  id: "prop-1",
  property_number: "PRP-0000004",
  customer_number: "CUS-0000042",
  customer_name: "Mara Example",
  country_code: "GB",
  property_type: "house",
  address: "12 Synthetic Street, Testville",
  purchase_price: 40_000_000,
  currency: "GBP",
  latest_valuation: { id: "val-1", valuation_number: "VAL-0000009", method: "surveyor", value: 39_500_000, currency: "GBP", valued_on: "2026-10-30", notes: null },
  charged_loan_number: null,
  created_at: "2026-10-30T00:00:00Z",
};
const offer = (overrides: Partial<MortgageOffer>): MortgageOffer => ({
  id: "mof-1",
  offer_number: "MOF-0000001",
  customer_number: "CUS-0000042",
  property_number: "PRP-0000004",
  product_code: "home-75",
  loan_amount: 10_000_000,
  currency: "GBP",
  term_months: 300,
  annual_rate_bps: 449,
  monthly_payment: 55_590,
  ltv_bps: 2532,
  status: "pending",
  expired: false,
  expires_on: null,
  loan_number: null,
  created_at: "2026-10-31T00:00:00Z",
  ...overrides,
});
const quote: Quote = {
  eligible: false,
  checks: [
    { rule: "loan_to_value", passed: true, detail: "25.32 % of the lower of valuation and price; the product allows 75 %." },
    { rule: "affordability", passed: false, detail: "The payment is 56% of declared monthly income; at most 35%." },
  ],
  currency: "GBP",
  loan_amount: 10_000_000,
  term_months: 300,
  annual_rate_bps: 449,
  monthly_payment: 55_590,
  ltv_bps: 2532,
  valuation_number: "VAL-0000009",
  valuation_method: "surveyor",
  income_estimate: 600_000,
  credit_score: 744,
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/mortgages/summary/counts": () => jsonResponse({ properties: 1, pending: 1, offered: 1, accepted: 1, active_mortgages: 2 }),
  "GET /api/v1/mortgages/products": () => jsonResponse(products),
  "GET /api/v1/mortgages/properties": () => jsonResponse(page([property])),
  "GET /api/v1/mortgages/offers": () =>
    jsonResponse(
      page([
        offer({}),
        offer({ id: "mof-2", offer_number: "MOF-0000002", status: "offered", expires_on: "2027-01-29" }),
        offer({ id: "mof-3", offer_number: "MOF-0000003", status: "accepted" }),
      ]),
    ),
};

describe("Mortgages page", () => {
  it("shows products, properties with their valuation, and offers", async () => {
    mockApi(routes);
    renderApp("/mortgages");
    const products = await screen.findByRole("table", { name: "Mortgage products" });
    expect(await within(products).findByText("ATLAS Home 90")).toBeInTheDocument();
    expect(within(products).getByText(/up to 90 % loan-to-value · 5.79 % fixed/)).toBeInTheDocument();
    const properties = screen.getByRole("table", { name: "Properties" });
    expect(await within(properties).findByText("PRP-0000004")).toBeInTheDocument();
    expect(within(properties).getByText(/surveyor £395,000.00 on 2026-10-30/)).toBeInTheDocument();
    const offers = screen.getByRole("table", { name: "Offers" });
    expect(await within(offers).findByText("MOF-0000002")).toBeInTheDocument();
    const offered = within(offers).getByText("MOF-0000002").closest("tr") as HTMLElement;
    expect(offered).toHaveTextContent("25 years · LTV 25.32 % · £555.90 a month · until 2027-01-29");
    const summary = (await screen.findByText("Active mortgages")).closest("div") as HTMLElement;
    expect(within(summary).getByText("2")).toBeInTheDocument();
  });

  it("registers, values, checks eligibility, applies and moves offers along", async () => {
    const api = mockApi({
      ...routes,
      "GET /api/v1/customers": () => jsonResponse(page([{ customer_number: "CUS-0000042", currency: "GBP" }])),
      "POST /api/v1/mortgages/properties": () => jsonResponse({ ...property, id: "prop-2" }, 201),
      "POST /api/v1/mortgages/properties/prop-1/valuations": () => jsonResponse(property.latest_valuation, 201),
      "POST /api/v1/mortgages/quote": () => jsonResponse(quote),
      "POST /api/v1/mortgages/offers": () => jsonResponse(offer({ id: "mof-9", offer_number: "MOF-0000009" }), 201),
      "POST /api/v1/mortgages/offers/mof-1/decide": () => jsonResponse(offer({ status: "offered" })),
      "POST /api/v1/mortgages/offers/mof-2/accept": () => jsonResponse(offer({ id: "mof-2", status: "accepted" })),
      "POST /api/v1/mortgages/offers/mof-3/complete": () => jsonResponse(offer({ id: "mof-3", status: "completed", loan_number: "LN-00000077" })),
    });
    renderApp("/mortgages");

    const register = await screen.findByRole("form", { name: "Register a property" });
    await userEvent.type(within(register).getByLabelText("Customer"), "CUS-0000042");
    await userEvent.selectOptions(within(register).getByLabelText("Property type"), "flat");
    await userEvent.type(within(register).getByLabelText("Purchase price"), "250000");
    await userEvent.click(within(register).getByRole("button", { name: "Register" }));

    await userEvent.click(await screen.findByRole("button", { name: "Desktop valuation PRP-0000004" }));
    const survey = screen.getByRole("form", { name: "Surveyor valuation" });
    await userEvent.type(within(survey).getByLabelText("Surveyed value"), "395000");
    await userEvent.click(within(survey).getByRole("button", { name: "Record survey" }));

    const form = screen.getByRole("form", { name: "Mortgage application" });
    await userEvent.type(within(form).getByLabelText("Applicant"), "CUS-0000042");
    await userEvent.type(within(form).getByLabelText("Property number"), "PRP-0000004");
    await userEvent.type(within(form).getByLabelText("Drawdown account"), "GB000000000101");
    await userEvent.type(within(form).getByLabelText("Loan amount"), "100000");
    await userEvent.type(within(form).getByLabelText("Declared monthly income"), "1000");
    await userEvent.click(within(form).getByRole("button", { name: "Check eligibility" }));
    const eligibility = await screen.findByLabelText("Eligibility");
    expect(eligibility).toHaveTextContent("Not eligible · loan-to-value 25.32 %");
    expect(eligibility).toHaveTextContent("✗ Affordability: The payment is 56% of declared monthly income");
    await userEvent.click(within(form).getByRole("button", { name: "Apply" }));
    expect(await screen.findByText("MOF-0000009 recorded: waiting for an underwriter.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Approve MOF-0000001" }));
    await userEvent.click(screen.getByRole("button", { name: "Accept MOF-0000002" }));
    await userEvent.click(screen.getByRole("button", { name: "Complete MOF-0000003" }));

    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(8));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/mortgages/properties"]).toEqual({ customer_number: "CUS-0000042", property_type: "flat", purchase_price: 25_000_000 });
    expect(bodies["POST /api/v1/mortgages/offers"]).toEqual({
      customer_number: "CUS-0000042",
      property_number: "PRP-0000004",
      product_code: "home-75",
      account_number: "GB000000000101",
      loan_amount: 10_000_000,
      term_years: 25,
      declared_monthly_income: 100_000,
    });
    expect(bodies["POST /api/v1/mortgages/offers/mof-1/decide"]).toEqual({ approve: true });
  });

  it("finds the customer's currency whatever the case of the number typed (PR #27 review)", async () => {
    const api = mockApi({
      ...routes,
      "GET /api/v1/customers": () => jsonResponse(page([{ customer_number: "CUS-0000042", currency: "GBP" }])),
      "POST /api/v1/mortgages/properties": () => jsonResponse({ ...property, id: "prop-2" }, 201),
    });
    renderApp("/mortgages");
    const register = await screen.findByRole("form", { name: "Register a property" });
    await userEvent.type(within(register).getByLabelText("Customer"), "cus-0000042");
    await userEvent.type(within(register).getByLabelText("Purchase price"), "250000");
    await userEvent.click(within(register).getByRole("button", { name: "Register" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method === "POST")).toHaveLength(1));
    expect(api.requests.find((r) => r.method === "POST")?.body).toMatchObject({ purchase_price: 25_000_000 });
  });

  it("is read-only without the permissions", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["loans:read"] }) });
    renderApp("/mortgages");
    expect(await screen.findByText("PRP-0000004")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Register a property" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Mortgage application" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Surveyor valuation" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Approve / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Complete / })).not.toBeInTheDocument();
  });
});
