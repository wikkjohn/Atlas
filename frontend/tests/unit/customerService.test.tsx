import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ServiceCase } from "@/types/customerService";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const soon = new Date(Date.now() + 3 * 3_600_000 + 60_000).toISOString();
const complaint: ServiceCase = {
  id: "srv-1",
  case_number: "SRV-0000001",
  customer_number: "CUS-0000042",
  customer_name: "Synthetic Customer",
  account_number: "US000000000101",
  category: "complaint",
  channel: "email",
  topic: "fees",
  priority: "normal",
  subject: "Fee charged twice",
  description: "The monthly fee was taken twice.",
  status: "open",
  opened_at: "2026-11-01T09:00:00Z",
  first_response_due: soon,
  resolve_due: soon,
  first_responded_at: null,
  response_breached: false,
  resolution_breached: false,
  escalated: false,
  resolved_at: null,
  resolution: null,
  outcome: null,
  redress_amount: null,
  redress_status: null,
  redress_entry: null,
  currency: "USD",
};
const breached: ServiceCase = { ...complaint, id: "srv-2", case_number: "SRV-0000002", category: "request", subject: "Replacement card", priority: "high", response_breached: true, escalated: true };

const routes = {
  ...healthyRoutes,
  "GET /api/v1/customer-service/summary/counts": () => jsonResponse({ open: 2, awaiting_customer: 0, complaints_open: 1, breached: 1, due_today: 2, redress_to_approve: 0, avg_first_response_minutes: 42.5 }),
  "GET /api/v1/customer-service/cases": () => jsonResponse(page([complaint, breached])),
};

describe("Customer Service page", () => {
  it("shows the summary and cases with their SLA timers", async () => {
    mockApi(routes);
    renderApp("/customer-service");
    expect(await screen.findByLabelText("Service summary")).toHaveTextContent("Avg first response42.5 min");
    const table = await screen.findByRole("table", { name: "Cases" });
    const first = (await within(table).findByText("SRV-0000001")).closest("tr");
    expect(first).toHaveTextContent("Fee charged twice · Complaint");
    expect(first).toHaveTextContent("Response due in 3 h · resolution due in 3 h");
    expect(within(table).getByText("SRV-0000002").closest("tr")).toHaveTextContent("Response breached · resolution due in 3 h · escalated");
  });

  it("opens a case, responds, proposes and pays redress, and resolves with an outcome", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/customer-service/cases": () => jsonResponse({ ...complaint, id: "srv-3", case_number: "SRV-0000003" }, 201),
      "POST /api/v1/customer-service/cases/srv-1/respond": () => jsonResponse({ ...complaint, first_responded_at: "2026-11-01T09:10:00Z" }),
      "POST /api/v1/customer-service/cases/srv-1/redress": () => jsonResponse({ ...complaint, redress_amount: 1_500, redress_status: "proposed" }),
      "POST /api/v1/customer-service/cases/srv-1/resolve": () => jsonResponse({ ...complaint, status: "resolved" }),
    });
    renderApp("/customer-service");
    const form = await screen.findByRole("form", { name: "Open case" });
    await userEvent.type(within(form).getByLabelText("Customer number"), "CUS-0000042");
    await userEvent.selectOptions(within(form).getByLabelText("Category"), "complaint");
    await userEvent.type(within(form).getByLabelText("Subject"), "Fee charged twice");
    await userEvent.type(within(form).getByLabelText("Description"), "Taken twice in October");
    await userEvent.click(within(form).getByRole("button", { name: "Open case" }));
    expect(await within(form).findByRole("status")).toHaveTextContent("SRV-0000003 opened");
    await userEvent.click(screen.getByRole("button", { name: "Respond to SRV-0000001" }));
    await userEvent.type(screen.getByLabelText("Redress for SRV-0000001"), "15");
    await userEvent.click(screen.getByRole("button", { name: "Propose redress on SRV-0000001" }));
    await userEvent.selectOptions(screen.getByLabelText("Outcome for SRV-0000001"), "partly_upheld");
    await userEvent.click(screen.getByRole("button", { name: "Resolve SRV-0000001" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(4));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/customer-service/cases"]).toMatchObject({ customer_number: "CUS-0000042", category: "complaint", channel: "phone", topic: "card", priority: "normal" });
    expect(bodies["POST /api/v1/customer-service/cases/srv-1/redress"]).toEqual({ amount: 1_500, account_number: "US000000000101" });
    expect(bodies["POST /api/v1/customer-service/cases/srv-1/resolve"]).toEqual({ resolution: "Final response sent", outcome: "partly_upheld" });
  });

  it("is read-only with only service:read", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["service:read"] }) });
    renderApp("/customer-service");
    expect(await screen.findByText("SRV-0000001")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Open case" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Respond to SRV-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run SLA sweep" })).not.toBeInTheDocument();
  });
});
