import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { base32Decode, codeAt } from "@/services/totp";
import type { AuthSessionInfo } from "@/types/enterprise";

import { adminUser, authRoutes, healthyRoutes, jsonResponse, mockApi } from "./fixtures";
import { renderApp } from "./render";

const expires = () => new Date(Date.now() + 3_600_000).toISOString();
const signedIn = (user = adminUser) => ({
  status: "signed_in",
  access_token: "fresh-token",
  token_type: "bearer",
  expires_at: expires(),
  user,
  challenge_token: null,
  challenge_expires_at: null,
});

const session: AuthSessionInfo = {
  id: "s1",
  method: "password",
  provider: null,
  mfa: "not_required",
  ip_address: "127.0.0.1",
  user_agent: "test",
  created_at: "2026-11-05T10:00:00Z",
  last_seen_at: "2026-11-05T10:05:00Z",
  expires_at: "2026-11-05T22:00:00Z",
  revoked_at: null,
  revoked_reason: null,
  current: true,
};

describe("Authenticator codes", () => {
  it("match RFC 6238's SHA-1 test vector", async () => {
    // The ASCII secret "12345678901234567890", base32-encoded, at T = 59 s (step 1).
    const secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";
    expect(Array.from(base32Decode(secret).slice(0, 3))).toEqual([0x31, 0x32, 0x33]);
    expect(await codeAt(secret, 1)).toBe("287082");
    expect(await codeAt(secret, Math.floor(1111111109 / 30))).toBe("081804");
  });
});

describe("Signing in (Phase 84)", () => {
  it("asks for the second factor when the user has one", async () => {
    const api = mockApi({
      ...healthyRoutes,
      "POST /api/v1/auth/login": () =>
        jsonResponse({
          status: "mfa_required",
          access_token: null,
          token_type: "bearer",
          expires_at: null,
          user: null,
          challenge_token: "challenge-1",
          challenge_expires_at: expires(),
        }),
      "POST /api/v1/auth/mfa/verify": () => jsonResponse(signedIn()),
    });
    renderApp("/", { signedIn: false });
    await userEvent.type(await screen.findByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "atlas-demo-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const form = await screen.findByRole("form", { name: "Second factor" });
    expect(sessionStorage.getItem("atlas.session")).toBeNull();
    await userEvent.type(within(form).getByLabelText("Code"), "123456");
    await userEvent.click(within(form).getByRole("button", { name: "Verify" }));

    await screen.findByText("All systems operational");
    const verify = api.requests.find((r) => r.path === "/api/v1/auth/mfa/verify");
    expect(verify?.body).toEqual({ challenge_token: "challenge-1", code: "123456" });
    expect(verify?.headers.Authorization).toBeUndefined();
    expect(JSON.parse(sessionStorage.getItem("atlas.session") ?? "{}").token).toBe("fresh-token");
  });

  it("signs in through the simulated corporate directory", async () => {
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/auth/sso/providers": () =>
        jsonResponse([{ id: "atlas-directory", name: "ATLAS Corporate Directory", simulated: true }]),
      "POST /api/v1/auth/sso/atlas-directory/start": () =>
        jsonResponse({ provider: "atlas-directory", state: "state-1", nonce: "nonce-1", expires_at: expires() }),
      "POST /api/v1/simulated-directory/atlas-directory/sign-in": () => jsonResponse({ id_token: "id-token-1" }),
      "POST /api/v1/auth/sso/atlas-directory/callback": () =>
        jsonResponse(signedIn({ ...adminUser, session: { ...session, method: "sso", provider: "atlas-directory" } })),
    });
    renderApp("/", { signedIn: false });
    await userEvent.click(
      await screen.findByRole("button", { name: "Continue with ATLAS Corporate Directory (simulated SSO)" }),
    );
    const directory = await screen.findByRole("form", { name: "ATLAS Corporate Directory" });
    await userEvent.type(within(directory).getByLabelText("Directory username"), "admin");
    await userEvent.type(within(directory).getByLabelText("Directory password"), "atlas-demo-password");
    await userEvent.click(within(directory).getByRole("button", { name: "Continue to ATLAS Global Bank" }));

    await screen.findByText("All systems operational");
    const signIn = api.requests.find((r) => r.path.endsWith("/sign-in"));
    expect(signIn?.body).toEqual({ nonce: "nonce-1", username: "admin", password: "atlas-demo-password", otp: null });
    const callback = api.requests.find((r) => r.path.endsWith("/callback"));
    expect(callback?.body).toEqual({ state: "state-1", id_token: "id-token-1" });
  });
});

describe("Security page (Phase 84)", () => {
  it("holds a role that requires a factor on enrolment, with a working simulated authenticator", async () => {
    const owed = { ...adminUser, mfa_enabled: false, mfa_enrolment_required: true, scope: { countries: ["GB"], departments: null } };
    let current = owed;
    const secret = "JBSWY3DPEHPK3PXP";
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/auth/me": () => jsonResponse(current),
      "GET /api/v1/auth/sessions": () => jsonResponse([session]),
      "POST /api/v1/auth/mfa/enrol": () =>
        jsonResponse({ secret, provisioning_uri: `otpauth://totp/ATLAS:admin?secret=${secret}` }),
      "POST /api/v1/auth/mfa/confirm": () => {
        current = { ...owed, mfa_enabled: true, mfa_enrolment_required: false, mfa_recovery_codes_left: 8 } as typeof owed;
        return jsonResponse({ recovery_codes: ["AAAA-BBBB", "CCCC-DDDD"] });
      },
    });
    renderApp("/customers");

    expect(await screen.findByRole("heading", { name: "Security" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Your role requires a second factor");
    expect(screen.getByLabelText("Country scope")).toHaveTextContent("GB");
    expect(screen.getByLabelText("Department scope")).toHaveTextContent("All departments");
    expect(await screen.findByRole("table", { name: "Sessions" })).toHaveTextContent("This session");

    await userEvent.click(screen.getByRole("button", { name: "Set up an authenticator" }));
    expect(await screen.findByLabelText("Secret")).toHaveTextContent(secret);
    const shown = await screen.findByTestId("authenticator-code");
    await waitFor(() => expect(shown.textContent).toMatch(/^\d{6}$/));
    const code = shown.textContent ?? "";
    expect([await codeAt(secret, Math.floor(Date.now() / 30_000)), await codeAt(secret, Math.floor(Date.now() / 30_000) - 1)]).toContain(code);

    await userEvent.type(screen.getByLabelText("Code from the authenticator"), code);
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByLabelText("Recovery codes")).toHaveTextContent("AAAA-BBBB");
    expect(api.requests.find((r) => r.path === "/api/v1/auth/mfa/confirm")?.body).toEqual({ code });
    expect(await screen.findByText(/8 recovery code\(s\) left/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("is reachable from the user menu", async () => {
    mockApi({ ...healthyRoutes, ...authRoutes(adminUser), "GET /api/v1/auth/sessions": () => jsonResponse([session]) });
    renderApp("/");
    await userEvent.click(await screen.findByRole("link", { name: "Security" }));
    expect(await screen.findByRole("heading", { name: "Security" })).toBeInTheDocument();
    expect(screen.getByLabelText("Country scope")).toHaveTextContent("All countries");
  });
});
