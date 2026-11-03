import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { analyst, manager } from "./enterprise-fixtures";
import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const restricted = { ...analyst, annual_compensation: null, compensation_currency: null };

function routes(list = [manager, analyst]) {
  return {
    ...healthyRoutes,
    "GET /api/v1/employees": () => jsonResponse(page(list, list.length, 25)),
    "GET /api/v1/employees/emp-2": () => jsonResponse(list[1]),
    "GET /api/v1/employees/emp-2/reporting-chain": () => jsonResponse([manager]),
    "GET /api/v1/employees/emp-2/direct-reports": () => jsonResponse([]),
    "GET /api/v1/organizations": () => jsonResponse(page([])),
    "GET /api/v1/roles": () => jsonResponse([]),
    "GET /api/v1/employees/workforce/summary": () => jsonResponse(workforce),
  };
}

const workforce = {
  employees: 150246,
  generated: 150000,
  countries: { DE: 31163, JP: 29771 },
  departments: { "Branch Network": 94945, "Customer Onboarding": 31695 },
  grades: { "1": 40907, "2": 40953, "9": 21 },
  roles: { banking_employee: 127989, department_manager: 89 },
  statuses: { active: 147238, on_leave: 3008 },
  top_skills: { "account-opening": 47266, "cash-handling": 35850 },
};

describe("Employees page", () => {
  it("shows the workforce in numbers and generates it for those who manage staff", async () => {
    const api = mockApi({ ...routes(), "POST /api/v1/employees/workforce/generate": () => jsonResponse({ created: 150000, existing: 0, seconds: 37 }) });
    renderApp("/employees");
    const panel = await screen.findByRole("region", { name: "Workforce" });
    expect(await within(panel).findByText("150,246 employees (150,000 generated)")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Grades")).toHaveTextContent("Grades: 1: 40,907 · 2: 40,953 · 9: 21");
    expect(panel).toHaveTextContent("Departments: Branch Network 94,945");
    const form = within(panel).getByRole("form", { name: "Generate workforce" });
    await userEvent.click(within(form).getByRole("button", { name: "Generate workforce" }));
    expect(await within(form).findByRole("status")).toHaveTextContent("150,000 created (0 already there) in 37 s");
    expect(api.requests.find((r) => r.method === "POST")?.body).toEqual({ count: 150000, seed: 2030 });
  });

  it("does not offer to generate the workforce without employees:manage", async () => {
    mockApi({ ...routes(), ...authRoutes({ ...employeeUser, permissions: ["employees:read"] }) });
    renderApp("/employees");
    expect(await screen.findByRole("region", { name: "Workforce" })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Generate workforce" })).not.toBeInTheDocument();
  });

  it("formats compensation in the employee's currency", async () => {
    mockApi(routes());
    renderApp("/employees");

    const row = (await screen.findByText("Ren Ito")).closest("tr") as HTMLElement;
    // JPY has no minor unit: 6,500,000 minor units is ¥6,500,000.
    expect(within(row).getByText("¥6,500,000")).toBeInTheDocument();
  });

  it("shows compensation as restricted when the API withholds it", async () => {
    mockApi({ ...routes([manager, restricted]), ...authRoutes(employeeUser) });
    renderApp("/employees");

    const row = (await screen.findByText("Ren Ito")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Restricted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hire employee" })).not.toBeInTheDocument();
  });

  it("opens a profile with the reporting chain", async () => {
    mockApi(routes());
    renderApp("/employees");

    await userEvent.click(await screen.findByRole("button", { name: "Ren Ito" }));

    const dialog = await screen.findByRole("dialog", { name: "Employee profile" });
    const chain = await within(dialog).findByRole("region", { name: "Reporting chain" });
    expect(within(chain).getByRole("button", { name: "Aiko Tanaka" })).toBeInTheDocument();
    expect(within(dialog).getByText(/AGB-0000002/)).toBeInTheDocument();
  });

  it("sends the search term to the API", async () => {
    const api = mockApi(routes());
    renderApp("/employees");

    await userEvent.type(await screen.findByRole("textbox", { name: "Search employees" }), "tanaka{enter}");

    await screen.findByText("Ren Ito");
    expect(api.requests.some((r) => r.path === "/api/v1/employees" && r.search.get("q") === "tanaka")).toBe(true);
  });

  it("lists access requests raised by hires and grants one (Phase 74)", async () => {
    const requested = { id: "ag-1", grant_number: "AG-0000001", employee_id: "emp-9", employee_number: "AGB-0000009", employee_name: "Rina Okafor", profile: "role:banking_employee", status: "requested", requested_at: "2026-11-03T10:00:00Z", granted_at: null, revoked_at: null, revoke_reason: null };
    const api = mockApi({
      ...routes(),
      "GET /api/v1/access/grants": (r: { search: URLSearchParams }) => jsonResponse(r.search.get("status") === "requested" ? [requested] : []),
      "POST /api/v1/access/grants/ag-1/grant": () => jsonResponse({ ...requested, status: "granted", granted_at: "2026-11-03T11:00:00Z" }),
    });
    renderApp("/employees");
    const panel = await screen.findByRole("region", { name: "Systems access" });
    expect(await within(panel).findByText(/AG-0000001 · Rina Okafor \(AGB-0000009\) · role:banking_employee · requested/)).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Grant access" }));
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST" && r.path.endsWith("/ag-1/grant"))).toBe(true));
    await userEvent.selectOptions(within(panel).getByLabelText("Access status"), "revoked");
    expect(await within(panel).findByText("No revoked access grants.")).toBeInTheDocument();
  });
});
