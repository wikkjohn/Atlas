import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { pendingCustomer, tellerUser, verifiedCustomer } from "./banking-fixtures";
import { authRoutes, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

function routes(customer = pendingCustomer) {
  return {
    ...healthyRoutes,
    "GET /api/v1/customers": () => jsonResponse(page([pendingCustomer, verifiedCustomer])),
    [`GET /api/v1/customers/${customer.id}`]: () => jsonResponse(customer),
    "GET /api/v1/accounts": () => jsonResponse(page([])),
    "GET /api/v1/account-requests": () => jsonResponse(page([])),
    "GET /api/v1/countries": () => jsonResponse(page([])),
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
});
