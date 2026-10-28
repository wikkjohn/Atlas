import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  databaseDownHealth,
  healthyRoutes,
  jsonResponse,
  mockApi,
  systemStatus,
} from "./fixtures";
import { renderApp } from "./render";

describe("Overview page", () => {
  it("shows every enterprise metric from the analytics endpoint, linked to its screen", async () => {
    mockApi(healthyRoutes);
    renderApp();

    const metrics = await screen.findByRole("region", { name: "Key metrics" });
    const employees = await within(metrics).findByRole("link", { name: "Employees: 131" });
    expect(employees).toHaveAttribute("href", "/employees");
    for (const label of [
      "Configured countries: 5",
      "Registered workflows: 1",
      "Active simulation runs: 1",
      "Completed workflow executions: 14",
      "Failed workflow executions: 1",
      "Customer accounts created: 120",
      "Registered AI tools: 2",
      "Completed experiments: 3",
      "Average process duration: 3.35 h",
    ]) {
      expect(within(metrics).getByRole("link", { name: label })).toBeInTheDocument();
    }
    const cost = within(metrics).getByRole("link", { name: /Estimated simulation operating cost/ });
    expect(cost).toHaveTextContent("Estimate");
    expect(cost).toHaveAttribute("href", "/benchmarking");

    expect(screen.getByRole("list", { name: "Live executions by status" })).toHaveTextContent("Failed");
    expect(screen.getByRole("link", { name: "5 open tasks" })).toHaveAttribute("href", "/workflows?tab=tasks");
    expect(screen.getByRole("list", { name: "Recent simulation runs" })).toHaveTextContent("Run #4");
    expect(screen.getByRole("list", { name: "Recent experiments" })).toHaveTextContent("Successful");
  });

  it("shows platform health tiles below the metrics", async () => {
    mockApi(healthyRoutes);
    renderApp();
    const database = await screen.findByRole("group", { name: "Database" });
    expect(await within(database).findByText("Connected")).toBeInTheDocument();
    expect(within(database).getByText(/2.5 ms round trip/)).toBeInTheDocument();
    const migrations = screen.getByRole("group", { name: "Schema migrations" });
    expect(await within(migrations).findByText("Up to date")).toBeInTheDocument();
    const redis = screen.getByRole("group", { name: "Redis cache" });
    expect(within(redis).getByText("Not configured")).toBeInTheDocument();
    expect(await screen.findByText("All systems operational")).toBeInTheDocument();
  });

  it("shows an analytics failure visibly", async () => {
    mockApi({
      ...healthyRoutes,
      "/api/v1/analytics/overview": () =>
        jsonResponse({ error: { code: "internal_error", message: "Metrics unavailable", details: null, correlation_id: "c1" } }, 500),
    });
    renderApp();
    expect(await screen.findByText(/Metrics unavailable/)).toBeInTheDocument();
  });
});

describe("System Settings page", () => {
  it("shows platform, database and module details", async () => {
    mockApi({ ...healthyRoutes, "/api/v1/roles": () => jsonResponse([]), "/api/v1/users": () => jsonResponse({ items: [], total: 0, limit: 20, offset: 0 }) });
    renderApp("/settings");
    expect(await screen.findByText("PostgreSQL 16.4")).toBeInTheDocument();

    const roadmap = screen.getByRole("region", { name: "Module roadmap" });
    const rows = within(roadmap).getAllByRole("row");
    // Header + 2 modules, sorted by phase.
    expect(rows).toHaveLength(3);
    expect(within(rows[1]).getByText("Platform core")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Available")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Planned")).toBeInTheDocument();
  });
});

describe("Overview availability", () => {
  it("keeps the session through an outage at load and recovers on retry", async () => {
    let backendUp = false;
    mockApi(
      Object.fromEntries(
        Object.entries(healthyRoutes).map(([path, handler]) => [
          path,
          (request: Parameters<typeof handler>[0]) => {
            if (!backendUp) throw new TypeError("Failed to fetch");
            return handler(request);
          },
        ]),
      ),
    );
    renderApp();

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("The ATLAS API is unavailable")).toBeInTheDocument();
    // The user was not signed out by the outage.
    expect(screen.queryByRole("form", { name: "Sign in" })).not.toBeInTheDocument();

    backendUp = true;
    await userEvent.click(within(alert).getByRole("button", { name: /retry connection/i }));

    expect(await screen.findByText("All systems operational")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the failure state on the overview when the API fails mid-session", async () => {
    let backendUp = true;
    const failing = (handler: (typeof healthyRoutes)[string]) => (request: Parameters<typeof handler>[0]) => {
      if (!backendUp) throw new TypeError("Failed to fetch");
      return handler(request);
    };
    mockApi({
      ...healthyRoutes,
      "/api/health": failing(healthyRoutes["/api/health"]),
      "/api/system/info": failing(healthyRoutes["/api/system/info"]),
      "/api/system/status": failing(healthyRoutes["/api/system/status"]),
    });
    renderApp();
    expect(await screen.findByText("All systems operational")).toBeInTheDocument();

    backendUp = false;
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("The ATLAS API is unavailable")).toBeInTheDocument();
    expect(screen.getByText("API unreachable")).toBeInTheDocument();
  });

  it("treats a proxy 502 (backend down behind Vite) as unreachable", async () => {
    const badGateway = () => new Response("Bad Gateway", { status: 502 });
    mockApi({
      "/api/v1/auth/me": badGateway,
      "/api/health": badGateway,
      "/api/system/info": badGateway,
      "/api/system/status": badGateway,
    });
    renderApp();

    expect(await screen.findByText("The ATLAS API is unavailable")).toBeInTheDocument();
  });

  it("reports an unavailable database when health returns 503", async () => {
    mockApi({
      ...healthyRoutes,
      "/api/health": () => jsonResponse(databaseDownHealth, 503),
      "/api/system/status": () =>
        jsonResponse({
          ...systemStatus,
          status: "unavailable",
          database: {
            ...systemStatus.database,
            connected: false,
            error: "connection refused",
            migrations: null,
          },
        }),
    });
    renderApp();

    const database = await screen.findByRole("group", { name: "Database" });
    expect(await within(database).findByText("Unavailable")).toBeInTheDocument();
    expect(within(database).getByText("connection refused")).toBeInTheDocument();
    expect(screen.getByText("Database unavailable")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(screen.getByRole("group", { name: "Schema migrations" })).getByText(
          "Database unreachable",
        ),
      ).toBeInTheDocument(),
    );
  });

  it("flags pending migrations", async () => {
    mockApi({
      ...healthyRoutes,
      "/api/system/status": () =>
        jsonResponse({
          ...systemStatus,
          status: "needs_migration",
          database: {
            ...systemStatus.database,
            migrations: {
              current_revisions: [],
              head_revisions: ["0001_platform_baseline"],
              up_to_date: false,
            },
          },
        }),
    });
    renderApp();

    const migrations = await screen.findByRole("group", { name: "Schema migrations" });
    expect(await within(migrations).findByText("Pending")).toBeInTheDocument();
    expect(within(migrations).getByText(/Current none/)).toBeInTheDocument();
  });
});
