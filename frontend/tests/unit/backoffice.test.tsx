import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { DepartmentRequest, ThinDepartment } from "@/types/backoffice";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const counts = { submitted: 0, approved: 0, rejected: 0, completed: 0, overdue: 0, breached: 0 };
const legal: ThinDepartment = {
  code: "legal",
  name: "Legal",
  description: "Contracts, legal holds and litigation.",
  processes: [
    { code: "outside_counsel", name: "Outside counsel instruction", description: "Instruct external lawyers.", approval: true, sla_hours: 72, amount_label: "Fee estimate", budget_usd: 50_000, major_above_usd: 150_000, workflow_id: "WF-1100" },
    { code: "contract_review", name: "Contract review", description: "Review a contract.", approval: true, sla_hours: 120, amount_label: null, budget_usd: null, major_above_usd: null, workflow_id: "WF-1101" },
    { code: "legal_hold", name: "Legal hold", description: "Preserve records.", approval: false, sla_hours: 24, amount_label: null, budget_usd: null, major_above_usd: null, workflow_id: "WF-1102" },
  ],
  counts: { ...counts, submitted: 1, approved: 1, overdue: 1 },
};
const marketing: ThinDepartment = { ...legal, code: "marketing", name: "Marketing", description: "Campaigns.", counts };
const pending: DepartmentRequest = {
  id: "dr-1",
  request_number: "DR-0000001",
  department: "legal",
  process: "outside_counsel",
  process_name: "Outside counsel instruction",
  title: "Lease dispute",
  details: "",
  amount: 6_000_000,
  over_budget: true,
  needs_executive: false,
  status: "submitted",
  due_at: "2026-11-05T09:00:00Z",
  breached: false,
  note: null,
  created_at: "2026-11-02T09:00:00Z",
};
const approved: DepartmentRequest = { ...pending, id: "dr-2", request_number: "DR-0000002", process: "contract_review", process_name: "Contract review", title: "Supplier MSA", amount: null, over_budget: false, status: "approved" };

const routes = {
  ...healthyRoutes,
  "GET /api/v1/backoffice/departments": () => jsonResponse([legal, marketing]),
  "GET /api/v1/backoffice/requests": () => jsonResponse(page([pending, approved])),
};

describe("Departments page", () => {
  it("shows every department's counts, the selected one's processes and requests", async () => {
    mockApi(routes);
    renderApp("/departments");
    const grid = await screen.findByRole("list", { name: "Departments" });
    expect(within(grid).getByRole("button", { name: /Legal/ })).toHaveTextContent("1 to decide · 1 to complete · 0 done · 1 overdue");
    expect(within(grid).getByRole("button", { name: /Legal/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("list", { name: "Processes" })).toHaveTextContent("executive above US$150,000");
    expect((await screen.findByText("DR-0000001")).closest("tr")).toHaveTextContent("over budget");
  });

  it("submits a request with its amount, decides and completes requests", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/backoffice/requests": () => jsonResponse({ ...pending, id: "dr-3", request_number: "DR-0000003" }, 201),
      "POST /api/v1/backoffice/requests/dr-1/reject": () => jsonResponse({ ...pending, status: "rejected" }),
      "POST /api/v1/backoffice/requests/dr-2/complete": () => jsonResponse({ ...approved, status: "completed" }),
    });
    renderApp("/departments");
    const form = await screen.findByRole("form", { name: "Submit request" });
    await userEvent.type(within(form).getByLabelText("Title"), "Lease dispute counsel");
    await userEvent.type(within(form).getByLabelText("Amount"), "40000");
    await userEvent.click(within(form).getByRole("button", { name: "Submit request" }));
    expect(await within(form).findByRole("status")).toHaveTextContent("DR-0000003 submitted");
    await userEvent.click(await screen.findByRole("button", { name: "Reject DR-0000001" }));
    await userEvent.click(screen.getByRole("button", { name: "Complete DR-0000002" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(3));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/backoffice/requests"]).toMatchObject({ department: "legal", process: "outside_counsel", title: "Lease dispute counsel", amount: 4_000_000 });
  });

  it("is read-only with only departments:read", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["departments:read"] }) });
    renderApp("/departments");
    expect(await screen.findByText("DR-0000001")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Submit request" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject DR-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Complete DR-0000002" })).not.toBeInTheDocument();
  });
});
