import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Role, UserAccount } from "@/types/enterprise";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const roles: Role[] = [
  { id: "r1", code: "platform_administrator", name: "Platform Administrator", description: "", permissions: ["users:read", "users:manage", "accounts:approve"] },
  { id: "r2", code: "banking_employee", name: "Banking Employee", description: "", permissions: ["accounts:request"] },
  { id: "r3", code: "automated_policy", name: "Automated Policy Engine", description: "", permissions: ["accounts:approve_low_risk"] },
];

const account = (partial: Partial<UserAccount>): UserAccount => ({
  id: "u2",
  username: "teller",
  email: "teller@atlasbank.example",
  display_name: "Demo Teller",
  role: "banking_employee",
  role_name: "Banking Employee",
  employee_id: null,
  is_active: true,
  last_login_at: null,
  created_at: "2026-10-27T00:00:00Z",
  is_service_account: false,
  ...partial,
});

const routes = {
  ...healthyRoutes,
  "GET /api/v1/roles": () => jsonResponse(roles),
  "GET /api/v1/users": (r: { search: URLSearchParams }) =>
    jsonResponse(
      page(
        r.search.get("kind") === "service"
          ? [account({ id: "u3", username: "atlas-policy-engine", display_name: "ATLAS Policy Engine (system)", role: "automated_policy", role_name: "Automated Policy Engine", is_service_account: true })]
          : [account({})],
      ),
    ),
};

describe("System Settings users and roles", () => {
  it("lets an administrator change roles, deactivate users and create accounts", async () => {
    const api = mockApi({
      ...routes,
      "PATCH /api/v1/users/u2": () => jsonResponse(account({ role: "platform_administrator" })),
      "POST /api/v1/users": () => jsonResponse(account({ id: "u9", username: "new.analyst" }), 201),
    });
    renderApp("/settings");

    const users = await screen.findByRole("table", { name: "Users" });
    const role = await within(users).findByLabelText("Role of teller");
    // Service roles are never offered to people.
    expect(within(role).queryByRole("option", { name: "Automated Policy Engine" })).toBeNull();
    await userEvent.selectOptions(role, "platform_administrator");
    await waitFor(() => expect(api.requests.find((r) => r.method === "PATCH")?.body).toEqual({ role: "platform_administrator" }));
    await userEvent.click(within(users).getByRole("button", { name: "Deactivate teller" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method === "PATCH").at(-1)?.body).toEqual({ is_active: false }));

    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    const form = await screen.findByRole("form", { name: "Create a user" });
    const submit = within(screen.getByRole("dialog")).getByRole("button", { name: "Create user" });
    await userEvent.type(within(form).getByLabelText("Username"), "New Analyst");
    await userEvent.type(within(form).getByLabelText("Initial password"), "short");
    await userEvent.click(submit);
    expect(within(form).getByText(/lower-case letters/)).toBeInTheDocument();
    expect(within(form).getByText("At least 12 characters.")).toBeInTheDocument();
    expect(api.requests.some((r) => r.method === "POST")).toBe(false);

    await userEvent.clear(within(form).getByLabelText("Username"));
    await userEvent.type(within(form).getByLabelText("Username"), "new.analyst");
    await userEvent.type(within(form).getByLabelText("Email"), "new.analyst@atlasbank.example");
    await userEvent.type(within(form).getByLabelText("Display name"), "New Analyst");
    await userEvent.type(within(form).getByLabelText("Initial password"), "-a-long-enough-password");
    await userEvent.click(submit);
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toMatchObject({
      username: "new.analyst",
      email: "new.analyst@atlasbank.example",
      role: "banking_employee",
    });
  });

  it("shows service accounts read-only apart from activation", async () => {
    mockApi(routes);
    renderApp("/settings");
    await userEvent.click(await screen.findByRole("tab", { name: "Service accounts" }));
    const users = screen.getByRole("table", { name: "Users" });
    expect(await within(users).findByText("ATLAS Policy Engine (system)")).toBeInTheDocument();
    expect(within(users).queryByLabelText("Role of atlas-policy-engine")).toBeNull();
    expect(within(users).getByText("Cannot sign in")).toBeInTheDocument();
    expect(within(users).getByRole("button", { name: "Deactivate atlas-policy-engine" })).toBeInTheDocument();
  });

  it("shows the role and permission matrix to everyone, users only with permission", async () => {
    mockApi({ ...routes, ...authRoutes(employeeUser) });
    renderApp("/settings");
    const matrix = await screen.findByRole("table", { name: "Role permissions" });
    expect(within(matrix).getByLabelText("Automated Policy Engine: accounts:approve_low_risk")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Users" })).not.toBeInTheDocument();
  });
});
