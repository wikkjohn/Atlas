import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Candidate, Department, LeaveRequest, Requisition, Shift } from "@/types/hr";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const dept: Department = { id: "dep-1", name: "Customer Onboarding", headcount: 12, country: "US", currency: "USD" };
const requisition: Requisition = {
  id: "req-1",
  requisition_number: "REQ-0000001",
  department: "Customer Onboarding",
  job_title: "Onboarding Adviser",
  role: "banking_employee",
  openings: 2,
  filled: 0,
  salary_min: 4_000_000,
  salary_max: 5_000_000,
  currency: "USD",
  reason: "Two advisers left.",
  status: "approved",
  created_at: "2026-11-02T09:00:00Z",
};
const pending: Requisition = { ...requisition, id: "req-2", requisition_number: "REQ-0000002", status: "open" };
const candidate: Candidate = {
  id: "can-1",
  candidate_number: "CAN-0000001",
  requisition_number: "REQ-0000001",
  name: "Rina Okafor",
  status: "applied",
  offered_salary: null,
  start_date: null,
  employee_number: null,
};
const leave: LeaveRequest = {
  id: "lv-1",
  leave_number: "LV-0000001",
  employee_number: "AGB-0000042",
  employee_name: "Avery Lane",
  kind: "annual",
  start_date: "2026-11-09",
  end_date: "2026-11-13",
  days: 5,
  status: "requested",
  note: null,
  created_at: "2026-11-02T09:00:00Z",
};
const shift: Shift = { id: "sh-1", shift_number: "SHF-0000001", department: "Customer Onboarding", on: "2026-11-02", start_hour: 9, hours: 8, required: 2, rostered: ["AGB-0000042"] };

const routes = {
  ...healthyRoutes,
  "GET /api/v1/hr/summary/counts": () =>
    jsonResponse({ requisitions_to_approve: 1, requisitions_recruiting: 1, offers_out: 0, leave_to_decide: 1, on_leave_today: 2, onboarding_overdue: 0, shifts_today: 1 }),
  "GET /api/v1/hr/departments": () => jsonResponse([dept]),
  "GET /api/v1/hr/capacity": () =>
    jsonResponse({ department_id: "dep-1", department: "Customer Onboarding", on: "2026-11-02", headcount: 12, on_leave: 2, shifts: 1, rostered: 1, available: 1, available_by_role: { teller: 1 } }),
  "GET /api/v1/hr/requisitions": () => jsonResponse(page([requisition, pending])),
  "GET /api/v1/hr/candidates": () => jsonResponse([candidate]),
  "GET /api/v1/hr/leave": () => jsonResponse(page([leave])),
  "GET /api/v1/hr/shifts": () => jsonResponse([shift]),
  "GET /api/v1/hr/onboarding": () => jsonResponse([]),
};

describe("Human Resources page", () => {
  it("shows the summary, requisitions with candidates, leave, shifts and a department's capacity", async () => {
    mockApi(routes);
    renderApp("/hr");
    expect(await screen.findByLabelText("HR summary")).toHaveTextContent("On leave today2");
    const reqs = await screen.findByRole("table", { name: "Requisitions" });
    const row = (await within(reqs).findByText("REQ-0000001")).closest("tr");
    expect(row).toHaveTextContent("0/2 filled");
    expect(row).toHaveTextContent("CAN-0000001 Rina Okafor");
    expect((await screen.findByText("LV-0000001")).closest("tr")).toHaveTextContent("5 days");
    expect((await screen.findByText("SHF-0000001")).closest("tr")).toHaveTextContent("09:00 for 8 h · 1/2 rostered");
    const select = await screen.findByLabelText("Capacity department");
    await within(select).findByRole("option", { name: /Customer Onboarding/ });
    await userEvent.selectOptions(select, "dep-1");
    expect(await screen.findByLabelText("Capacity result")).toHaveTextContent("1 available of 12 · 2 on leave · 1 shifts, 1 rostered · 1 teller");
  });

  it("opens and approves a requisition, offers and hires, and decides leave", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/hr/requisitions": () => jsonResponse({ ...pending, id: "req-3", requisition_number: "REQ-0000003" }, 201),
      "POST /api/v1/hr/requisitions/req-2/approve": () => jsonResponse({ ...pending, status: "approved" }),
      "POST /api/v1/hr/candidates/can-1/offer": () => jsonResponse({ ...candidate, status: "offered", offered_salary: 4_500_000 }),
      "POST /api/v1/hr/leave/lv-1/approve": () => jsonResponse({ ...leave, status: "approved" }),
    });
    renderApp("/hr");
    const form = await screen.findByRole("form", { name: "Open requisition" });
    await within(within(form).getByLabelText("Department")).findByRole("option", { name: /Customer Onboarding/ });
    await userEvent.selectOptions(within(form).getByLabelText("Department"), "dep-1");
    await userEvent.type(within(form).getByLabelText("Job title"), "Adviser");
    await userEvent.type(within(form).getByLabelText("Salary from"), "40000");
    await userEvent.type(within(form).getByLabelText("Salary to"), "50000");
    await userEvent.type(within(form).getByLabelText("Reason"), "Queues are over target");
    await userEvent.click(within(form).getByRole("button", { name: "Open requisition" }));
    expect(await within(form).findByRole("status")).toHaveTextContent("REQ-0000003 opened");
    await userEvent.click(screen.getByRole("button", { name: "Approve REQ-0000002" }));
    await userEvent.type(screen.getByLabelText("Offer salary for CAN-0000001"), "45000");
    await userEvent.click(screen.getByRole("button", { name: "Offer CAN-0000001" }));
    await userEvent.click(screen.getByRole("button", { name: "Approve LV-0000001" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(4));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/hr/requisitions"]).toMatchObject({ department_id: "dep-1", job_title: "Adviser", role: "banking_employee", openings: 1, salary_min: 4_000_000, salary_max: 5_000_000 });
    expect(bodies["POST /api/v1/hr/candidates/can-1/offer"]).toMatchObject({ salary: 4_500_000 });
  });

  it("is read-only with only hr:read", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["hr:read"] }) });
    renderApp("/hr");
    expect(await screen.findByText("REQ-0000002")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Open requisition" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve REQ-0000002" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve LV-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add shift" })).not.toBeInTheDocument();
  });
});
