import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { AuditArchive, RetentionReview } from "@/types/governance";

import { healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const archiveRow = (partial: Partial<AuditArchive> = {}): AuditArchive => ({
  id: "a1",
  archive_number: 1,
  before: "2025-11-05T00:00:00Z",
  first_event_at: "2024-01-02T10:00:00Z",
  last_event_at: "2025-11-04T10:00:00Z",
  events: 1234,
  location: "audit-000001-abcd.jsonl.gz",
  bytes: 40960,
  sha256: "0123456789abcdef".repeat(4),
  previous_sha256: null,
  created_by: "user-1",
  created_at: "2026-11-05T10:00:00Z",
  verified_at: null,
  verification: null,
  ...partial,
});

const review: RetentionReview = {
  as_of: "2026-11-05T12:00:00Z",
  due_total: 7,
  last_run: null,
  classes: [
    { id: "auth_sessions", name: "Sign-in sessions", tables: ["auth_sessions"], purpose: "Who signed in", retention: "90 days after the session ended", days: 90, action: "delete", rows: 50, due: 7, cutoff: "2026-08-07T12:00:00Z", applied_by: null },
    { id: "audit_events", name: "Audit log", tables: ["audit_events"], purpose: "Who changed what", retention: "1 year online, then the audit-log archive (kept)", days: 365, action: "archive", rows: 900, due: 0, cutoff: "2025-11-05T12:00:00Z", applied_by: "the audit-log archive" },
    { id: "customers", name: "Customers", tables: ["customers"], purpose: "Synthetic customers", retention: "Kept: at least 10 years after the relationship ends", days: null, action: "keep", rows: 3000, due: 0, cutoff: null, applied_by: null },
  ],
};

describe("Audit-log archive (Phase 85)", () => {
  it("archives old events, verifies an archive and searches it", async () => {
    let archives: AuditArchive[] = [];
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/audit-events": () => jsonResponse(page([])),
      "GET /api/v1/audit-archives": () => jsonResponse(archives),
      "POST /api/v1/audit-archives": () => {
        archives = [archiveRow()];
        return jsonResponse(archives[0]);
      },
      "POST /api/v1/audit-archives/a1/verify": () => {
        archives = [archiveRow({ verification: { ok: false, problems: ["the file's digest does not match the record"], sha256: "x", events: 1234 } })];
        return jsonResponse(archives[0].verification);
      },
      "GET /api/v1/audit-archives/a1/events": () =>
        jsonResponse({ items: [{ id: "e1", actor_id: null, action: "auth.login", entity_type: "user", entity_id: "u1", timestamp: "2024-01-02T10:00:00Z", correlation_id: null, metadata: {} }], total: 1 }),
    });
    renderApp("/audit");
    expect(await screen.findByText("Nothing archived yet: every event is online.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Archive events older than (days)"));
    await userEvent.type(screen.getByLabelText("Archive events older than (days)"), "400");
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Archive #1: 1234 events moved.");
    expect(api.requests.find((r) => r.method === "POST" && r.path === "/api/v1/audit-archives")?.body).toEqual({ older_than_days: 400 });

    const table = await screen.findByRole("table", { name: "Audit archives" });
    expect(table).toHaveTextContent("0123456789ab…");
    await userEvent.click(within(table).getByRole("button", { name: "Verify archive 1" }));
    expect(await within(table).findByText("the file's digest does not match the record")).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: "Search archive 1" }));
    const found = await screen.findByRole("region", { name: "Archived events" });
    expect(await within(found).findByText(/auth\.login · user u1/)).toBeInTheDocument();
  });
});

describe("Data retention (Phase 85)", () => {
  it("shows the schedule and applies it", async () => {
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/data-retention": () => jsonResponse(review),
      "POST /api/v1/data-retention/apply": () =>
        jsonResponse({ run_number: 3, applied_at: "2026-11-05T12:01:00Z", results: { auth_sessions: { deleted: 7 }, audit_events: { archived: 0, archive_number: null } } }),
      "GET /api/v1/users": () => jsonResponse(page([])),
      "GET /api/v1/roles": () => jsonResponse([]),
    });
    renderApp("/settings");
    const table = await screen.findByRole("table", { name: "Retention schedule" });
    const sessions = within(table).getByText("Sign-in sessions").closest("tr")!;
    expect(sessions).toHaveTextContent("90 days after the session ended");
    expect(sessions).toHaveTextContent("Delete");
    expect(within(table).getByText("Customers").closest("tr")).toHaveTextContent("Keep");
    await userEvent.click(screen.getByRole("button", { name: "Apply the retention schedule" }));
    expect(await screen.findByText("Run #3: auth_sessions: 7 deleted, audit_events: 0 archived.")).toBeInTheDocument();
    await waitFor(() => expect(api.requests.some((r) => r.path === "/api/v1/data-retention/apply")).toBe(true));
  });
});

describe("Sign-in lockout (Phase 85)", () => {
  it("shows why the account is refused", async () => {
    mockApi({
      "POST /api/v1/auth/login": () =>
        jsonResponse(
          { error: { code: "unauthorized", message: "This account is locked after repeated failed sign-ins; try again in 15 minute(s) or ask an administrator to unlock it.", details: null, correlation_id: "c" } },
          401,
        ),
    });
    renderApp("/", { signedIn: false });
    await userEvent.type(await screen.findByLabelText("Username"), "teller");
    await userEvent.type(screen.getByLabelText("Password"), "whatever-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This account is locked after repeated failed sign-ins");
  });

  it("lets an administrator unlock a locked user", async () => {
    const locked = { id: "u2", username: "teller", email: "teller@atlasbank.example", display_name: "Demo Teller", role: "banking_employee", role_name: "Banking Employee", employee_id: null, is_active: true, last_login_at: null, created_at: "2026-10-27T00:00:00Z", is_service_account: false, locked_until: new Date(Date.now() + 600_000).toISOString() };
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/users": () => jsonResponse(page([locked])),
      "GET /api/v1/roles": () => jsonResponse([]),
      "GET /api/v1/data-retention": () => jsonResponse(review),
      "POST /api/v1/users/u2/unlock": () => jsonResponse({ ...locked, locked_until: null }),
    });
    renderApp("/settings");
    const users = await screen.findByRole("table", { name: "Users" });
    expect(await within(users).findByText(/Locked until/)).toBeInTheDocument();
    await userEvent.click(within(users).getByRole("button", { name: "Unlock teller" }));
    await waitFor(() => expect(api.requests.some((r) => r.path === "/api/v1/users/u2/unlock")).toBe(true));
  });
});

describe("Backups and recovery drills (Phase 87)", () => {
  it("shows the latest backup, the latest passing drill and the runs", async () => {
    const drill = {
      run_number: 2,
      kind: "drill" as const,
      ok: true,
      location: "var/backups/atlas-backup-20261105T120000Z",
      details: { measured: { backup_s: 6.5, rto_s: 2.2, rpo_s: 9.2, total_s: 9.2 } },
      started_at: "2026-11-05T12:00:00Z",
      finished_at: "2026-11-05T12:00:09Z",
    };
    const failed = { ...drill, run_number: 3, ok: false, details: { error: "pg_dump is not installed" } };
    const backup = { ...drill, run_number: 1, kind: "backup" as const, details: {} };
    mockApi({
      ...healthyRoutes,
      "GET /api/v1/audit-events": () => jsonResponse(page([])),
      "GET /api/v1/audit-archives": () => jsonResponse([]),
      "GET /api/v1/backups": () =>
        jsonResponse({ latest_backup: backup, latest_drill: drill, recovery_point_age_s: 5400, runs: [failed, drill, backup] }),
    });
    renderApp("/audit");
    const table = await screen.findByRole("table", { name: "Backup runs" });
    expect(screen.getByText(/RTO 2\.2 s/)).toBeInTheDocument();
    expect(screen.getByText("2 h")).toBeInTheDocument();
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(rows[1]).toHaveTextContent("Failed");
    expect(rows[1]).toHaveTextContent("pg_dump is not installed");
    expect(rows[2]).toHaveTextContent("restored and checked in 2.2 s (recovery point 9 s old)");
  });

  it("says when nothing has been backed up", async () => {
    mockApi({
      ...healthyRoutes,
      "GET /api/v1/audit-events": () => jsonResponse(page([])),
      "GET /api/v1/audit-archives": () => jsonResponse([]),
    });
    renderApp("/audit");
    expect(await screen.findByText(/No backup has been recorded/)).toBeInTheDocument();
    expect(screen.getByText("No backup")).toBeInTheDocument();
  });
});

describe("Archive search pagination (PR #76 review)", () => {
  it("pages through every matching archived event", async () => {
    const event = (n: number) => ({ id: `e${n}`, actor_id: null, action: "auth.login", entity_type: "user", entity_id: `u${n}`, timestamp: "2024-01-02T10:00:00Z", correlation_id: null, metadata: {} });
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/audit-events": () => jsonResponse(page([])),
      "GET /api/v1/audit-archives": () => jsonResponse([archiveRow()]),
      "GET /api/v1/audit-archives/a1/events": (r) => {
        const offset = Number(r.search.get("offset") ?? 0);
        return jsonResponse({ items: [event(offset + 1)], total: 120 });
      },
    });
    renderApp("/audit");
    const table = await screen.findByRole("table", { name: "Audit archives" });
    await userEvent.click(within(table).getByRole("button", { name: "Search archive 1" }));
    const found = await screen.findByRole("region", { name: "Archived events" });
    expect(await within(found).findByText(/user u1$/)).toBeInTheDocument();
    expect(within(found).getByText("1–50 of 120")).toBeInTheDocument();
    await userEvent.click(within(found).getByRole("button", { name: "Next" }));
    expect(await within(found).findByText(/user u51$/)).toBeInTheDocument();
    expect(within(found).getByText("51–100 of 120")).toBeInTheDocument();
    const offsets = api.requests.filter((r) => r.path === "/api/v1/audit-archives/a1/events").map((r) => r.search.get("offset"));
    expect(offsets).toEqual(expect.arrayContaining(["0", "50"]));
  });
});
