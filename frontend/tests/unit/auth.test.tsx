import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { adminUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const loginResponse = {
  access_token: "fresh-token",
  token_type: "bearer",
  expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  user: adminUser,
};

describe("Authentication", () => {
  it("redirects anonymous visitors to sign in, then back to where they were going", async () => {
    const api = mockApi({
      ...healthyRoutes,
      "POST /api/v1/auth/login": () => jsonResponse(loginResponse),
      "/api/v1/countries": () => jsonResponse(page([])),
    });
    renderApp("/countries", { signedIn: false });

    await userEvent.type(await screen.findByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "atlas-demo-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Countries" })).toBeInTheDocument();
    const login = api.requests.find((r) => r.path === "/api/v1/auth/login");
    expect(login?.body).toEqual({ username: "admin", password: "atlas-demo-password" });
    expect(login?.headers.Authorization).toBeUndefined();
    const countries = api.requests.find((r) => r.path === "/api/v1/countries");
    expect(countries?.headers.Authorization).toBe("Bearer fresh-token");
    expect(JSON.parse(sessionStorage.getItem("atlas.session") ?? "{}").token).toBe("fresh-token");
  });

  it("shows an error for invalid credentials", async () => {
    mockApi({
      "POST /api/v1/auth/login": () =>
        jsonResponse(
          { error: { code: "unauthorized", message: "Invalid username or password.", details: null, correlation_id: "c" } },
          401,
        ),
    });
    renderApp("/", { signedIn: false });

    await userEvent.type(await screen.findByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Invalid username or password.")).toBeInTheDocument();
    expect(sessionStorage.getItem("atlas.session")).toBeNull();
  });

  it("signs out and clears the stored session", async () => {
    mockApi(healthyRoutes);
    renderApp();

    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("form", { name: "Sign in" })).toBeInTheDocument();
    expect(sessionStorage.getItem("atlas.session")).toBeNull();
  });

  it("ends the session when the API rejects the token", async () => {
    let tokenValid = true;
    mockApi({
      ...healthyRoutes,
      "/api/v1/countries": () =>
        tokenValid
          ? jsonResponse(page([]))
          : jsonResponse(
              { error: { code: "unauthorized", message: "Access token has expired.", details: null, correlation_id: null } },
              401,
            ),
    });
    renderApp("/");
    await screen.findByText("All systems operational");

    tokenValid = false;
    await userEvent.click(screen.getByRole("link", { name: "Countries" }));

    expect(await screen.findByText(/session has ended/i)).toBeInTheDocument();
    await waitFor(() => expect(sessionStorage.getItem("atlas.session")).toBeNull());
  });
});
