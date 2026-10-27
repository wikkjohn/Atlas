import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { asiaHq, bank } from "./enterprise-fixtures";
import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

function orgRoutes() {
  return {
    ...healthyRoutes,
    "GET /api/v1/organizations": (request: { search: URLSearchParams }) => {
      if (request.search.get("root_only") === "true") return jsonResponse(page([bank]));
      if (request.search.get("parent_id") === bank.id) return jsonResponse(page([asiaHq]));
      return jsonResponse(page([]));
    },
    "GET /api/v1/organizations/org-bank": () => jsonResponse(bank),
    "GET /api/v1/organizations/org-bank/ancestors": () => jsonResponse([]),
    "GET /api/v1/organizations/org-apac": () => jsonResponse(asiaHq),
    "GET /api/v1/organizations/org-apac/ancestors": () => jsonResponse([bank]),
    "GET /api/v1/countries": () => jsonResponse(page([])),
  };
}

describe("Organization page", () => {
  it("loads the hierarchy lazily and shows details for the selected unit", async () => {
    const api = mockApi(orgRoutes());
    renderApp("/organization");

    const tree = await screen.findByRole("list", { name: "Organization hierarchy" });
    await userEvent.click(await within(tree).findByRole("button", { name: /^Asia-Pacific HQ/ }));

    expect(await screen.findByRole("heading", { name: "Asia-Pacific HQ" })).toBeInTheDocument();
    expect(screen.getByText("ATLAS Global Bank", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Asia-Pacific")).toBeInTheDocument();
    expect(
      api.requests.some((r) => r.path === "/api/v1/organizations" && r.search.get("parent_id") === bank.id),
    ).toBe(true);
    // The child type is decided by the parent's type.
    expect(screen.getByRole("button", { name: "Add country subsidiary" })).toBeInTheDocument();
  });

  it("surfaces business-rule violations from the API", async () => {
    mockApi({
      ...orgRoutes(),
      "POST /api/v1/organizations": () =>
        jsonResponse(
          {
            error: {
              code: "business_rule_violation",
              message: "A regional headquarters must specify its region.",
              details: null,
              correlation_id: "trace-7",
            },
          },
          422,
        ),
    });
    renderApp("/organization");

    await userEvent.click(await screen.findByRole("button", { name: "Add regional hq" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Name"), "Middle East HQ");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "A regional headquarters must specify its region.",
    );
  });

  it("offers no management actions to read-only roles", async () => {
    mockApi({ ...orgRoutes(), ...authRoutes(employeeUser) });
    renderApp("/organization");

    expect(await screen.findByRole("heading", { name: "ATLAS Global Bank" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Add / })).not.toBeInTheDocument();
  });
});
