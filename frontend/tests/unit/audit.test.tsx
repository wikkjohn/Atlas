import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { loginEvent } from "./enterprise-fixtures";
import { healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

describe("Audit Center", () => {
  it("lists events, expands metadata and filters by action", async () => {
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/audit-events": () => jsonResponse(page([loginEvent])),
    });
    renderApp("/audit");

    const row = (await screen.findByText("employee.updated")).closest("tr") as HTMLElement;
    expect(within(row).getByText("admin")).toBeInTheDocument();
    expect(within(row).getByText("trace-123")).toBeInTheDocument();

    await userEvent.click(row);
    expect(screen.getByLabelText("Event metadata")).toHaveTextContent('"changed": true');

    await userEvent.type(screen.getByRole("textbox", { name: "Action" }), "employee.*");
    await waitFor(() =>
      expect(api.requests.some((r) => r.search.get("action") === "employee.*")).toBe(true),
    );
  });

  it("explains when access is denied by the API", async () => {
    mockApi({
      ...healthyRoutes,
      "GET /api/v1/audit-events": () =>
        jsonResponse(
          {
            error: {
              code: "forbidden",
              message: "Your role does not grant the 'audit:read' permission.",
              details: null,
              correlation_id: "trace-403",
            },
          },
          403,
        ),
    });
    renderApp("/audit");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Access denied: Your role does not grant the 'audit:read' permission.",
    );
  });
});
