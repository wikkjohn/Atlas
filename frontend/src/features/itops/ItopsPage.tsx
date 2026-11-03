import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { humanize } from "@/services/format";
import {
  useAcknowledge,
  useApplicationDetail,
  useApplications,
  useChanges,
  useCloseIncident,
  useContract,
  useDecideChange,
  useDeclareOutage,
  useEndOutage,
  useEstateSummary,
  useGenerateEstate,
  useImplement,
  useIncidents,
  useItopsSummary,
  useOpenIncident,
  useOutages,
  useRaiseChange,
  useRegistry,
  useResolve,
  useSampleCalls,
  useSweep,
} from "@/services/itops";
import type { AppState, ChangeRequest, Incident, Outage } from "@/types/itops";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const LEVELS = ["high", "medium", "low"];
const INCIDENT_TONE: Record<Incident["status"], Tone> = { open: "bad", acknowledged: "warn", resolved: "good", closed: "neutral" };
const CHANGE_TONE: Record<ChangeRequest["status"], Tone> = { requested: "warn", approved: "good", rejected: "neutral", implemented: "good", failed: "bad" };
const RISK_TONE: Record<ChangeRequest["risk"], Tone> = { low: "good", medium: "warn", high: "bad" };
const when = (iso: string) => new Date(iso).toISOString().slice(0, 16).replace("T", " ");

function ApplicationSelect({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const apps = useApplications();
  return (
    <select aria-label={label} className={INPUT} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose an application</option>
      {apps.data?.items
        .filter((a) => a.status === "active")
        .map((a) => (
          <option key={a.id} value={a.application_number}>
            {a.name} (tier {a.tier})
          </option>
        ))}
    </select>
  );
}

const STATE_TONE: Record<AppState["status"], Tone> = { up: "good", degraded: "warn", down: "bad" };
const OUTAGE_TONE: Record<Outage["status"], Tone> = { scheduled: "neutral", in_force: "bad", ended: "good" };

/** Phase 64: how the simulated application answers calls, whether it is up, and a test. */
function ContractPanel({ id }: { id: string }) {
  const { can } = useAuth();
  const contract = useContract(id);
  const calls = useSampleCalls();
  const c = contract.data;
  return (
    <div aria-label="Simulated application" role="region" className="mb-2 rounded-md bg-slate-50 p-2">
      <ErrorMessage error={contract.error ?? calls.error} />
      {c && (
        <>
          <p className="mb-1">
            <StatusPill compact tone={STATE_TONE[c.state.status]} label={c.state.status} />
            {c.state.cause && c.state.cause !== c.application_number && ` because ${c.state.cause} is ${c.state.status} (${c.state.path.join(" → ")})`}
          </p>
          <p aria-label="Contract">
            Read {c.median_ms.read} ms median, {c.p95_ms.read} ms p95 · write {c.median_ms.write} ms median · {(c.error_rate * 100).toFixed(2)} % errors · timeout {c.timeout_ms} ms ·{" "}
            {c.sync_dependencies} synchronous dependencies · {c.blast_radius} applications fail if it goes down
          </p>
          {can("itops:manage") && (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => calls.mutate({ id, operation: "read", count: 100, seed: 2030 })}>
                Test 100 calls
              </Button>
              {calls.data && (
                <span role="status">
                  {calls.data.ok} ok, {calls.data.failed} failed
                  {Object.entries(calls.data.errors).map(([k, v]) => ` (${v} ${k})`)} · p50 {calls.data.p50_ms} ms, p95 {calls.data.p95_ms} ms
                </span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function OutagesPanel() {
  const { can } = useAuth();
  const outages = useOutages();
  const declare = useDeclareOutage();
  const end = useEndOutage();
  const [form, setForm] = useState({ application_number: "", kind: "down", reason: "" });
  return (
    <Panel title="Outages" subtitle="Take a simulated application down or degrade it. A down application fails every call, and so does everything that calls it, directly or through others (data and batch feeds aside). An outage opens an incident.">
      {can("itops:manage") && (
        <form
          aria-label="Declare outage"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            declare.mutate(form);
          }}
        >
          <ApplicationSelect label="Outage application" value={form.application_number} onChange={(v) => setForm({ ...form, application_number: v })} />
          <select aria-label="Outage kind" className={INPUT} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            <option value="down">Down</option>
            <option value="degraded">Degraded</option>
          </select>
          <input aria-label="Outage reason" placeholder="Why" className={`w-56 ${INPUT}`} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <Button size="sm" type="submit" disabled={!form.application_number || form.reason.trim().length < 5}>
            Declare outage
          </Button>
          {declare.data && (
            <span role="status">
              {declare.data.outage_number} {declare.data.kind}: {declare.data.failing} applications fail · {declare.data.incident_number}
            </span>
          )}
        </form>
      )}
      <ErrorMessage error={outages.error ?? declare.error ?? end.error} />
      <table aria-label="Outages" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {outages.data?.items.map((o) => (
            <tr key={o.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{o.outage_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {o.application} (tier {o.tier}) · {o.kind} · {o.reason} · from {when(o.starts_at)}
                {o.ends_at && ` to ${when(o.ends_at)}`}
                {o.kind === "down" && ` · ${o.failing} applications fail`}
                {o.incident_number && ` · ${o.incident_number}`}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={OUTAGE_TONE[o.status]} label={humanize(o.status)} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {o.status === "in_force" && can("itops:manage") && (
                  <Button size="sm" variant="secondary" aria-label={`End ${o.outage_number}`} onClick={() => end.mutate(o.id)}>
                    End
                  </Button>
                )}
              </td>
            </tr>
          ))}
          {outages.data && outages.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No outages.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

const TIER_TONE = (tier: number): Tone => (tier === 1 ? "bad" : tier === 2 ? "warn" : "neutral");

function ApplicationDetailPanel({ id }: { id: string }) {
  const detail = useApplicationDetail(id);
  const d = detail.data;
  return (
    <div aria-label="Application detail" role="region" className="mt-3 rounded-md border border-slate-200 p-3 text-xs text-slate-700">
      <ErrorMessage error={detail.error} />
      {d && (
        <>
          <p className="mb-2 text-sm font-semibold text-slate-900">
            {d.application.application_number} {d.application.name}
          </p>
          <p className="mb-2">
            {d.application.department} · tier {d.application.tier} · {d.application.technology} on {d.application.hosting.replace("_", " ")}
            {d.application.vendor && ` (${d.application.vendor})`} · owner {d.application.owner ?? "none"}
          </p>
          <ContractPanel id={id} />
          <p aria-label="If it stops" className="mb-2 font-semibold text-rose-800">
            If it stops: {d.impact.affected} applications affected ({d.impact.direct} directly, up to {d.impact.depth} steps away; tier 1: {d.impact.by_tier["1"] ?? 0}, tier 2: {d.impact.by_tier["2"] ?? 0}, tier 3:{" "}
            {d.impact.by_tier["3"] ?? 0}) across {d.impact.departments} departments
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="font-semibold">Relies on ({d.dependencies.length})</p>
              <ul aria-label="Relies on">
                {d.dependencies.map((x) => (
                  <li key={x.id}>
                    {x.application_number} {x.name} · {x.kind} · tier {x.tier}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="font-semibold">Relied on by ({d.dependents.length})</p>
              <ul aria-label="Relied on by">
                {d.dependents.slice(0, 25).map((x) => (
                  <li key={x.id}>
                    {x.application_number} {x.name} · {x.kind} · tier {x.tier}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function ApplicationsPanel() {
  const { can } = useAuth();
  const [filters, setFilters] = useState({ q: "", tier: "", offset: 0 });
  const [selected, setSelected] = useState("");
  const [estate, setEstate] = useState({ count: "2500", seed: "2030" });
  const apps = useRegistry(filters);
  const summary = useEstateSummary();
  const generate = useGenerateEstate();
  const page = apps.data;
  return (
    <Panel title="Application registry" subtitle="Every application with its owning department, tier, owner, technology and hosting, what it relies on and what relies on it. Tier 1: customers or money stop when it stops; tier 2: a department stops; tier 3: an inconvenience.">
      {summary.data && (
        <p aria-label="Estate summary" className="mb-2 text-xs text-slate-600">
          {summary.data.applications} applications ({summary.data.generated} generated) · {summary.data.dependencies} dependencies · tier 1: {summary.data.by_tier["1"] ?? 0}, tier 2:{" "}
          {summary.data.by_tier["2"] ?? 0}, tier 3: {summary.data.by_tier["3"] ?? 0}
        </p>
      )}
      <div className="mb-2 flex flex-wrap items-end gap-2 text-xs">
        <input aria-label="Search applications" placeholder="Name or APP-" className={`w-48 ${INPUT}`} value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value, offset: 0 })} />
        <select aria-label="Tier" className={INPUT} value={filters.tier} onChange={(e) => setFilters({ ...filters, tier: e.target.value, offset: 0 })}>
          <option value="">All tiers</option>
          {["1", "2", "3"].map((t) => (
            <option key={t} value={t}>
              Tier {t}
            </option>
          ))}
        </select>
        {can("itops:approve_major") && (
          <form
            aria-label="Generate estate"
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              generate.mutate({ count: Number(estate.count), seed: Number(estate.seed) });
            }}
          >
            <input aria-label="Applications to generate" type="number" min={1} max={10000} className={`w-20 ${INPUT}`} value={estate.count} onChange={(e) => setEstate({ ...estate, count: e.target.value })} />
            <input aria-label="Estate seed" type="number" min={0} className={`w-20 ${INPUT}`} value={estate.seed} onChange={(e) => setEstate({ ...estate, seed: e.target.value })} />
            <Button size="sm" variant="secondary" type="submit">
              Generate estate
            </Button>
            {generate.data && (
              <span role="status">
                {generate.data.created} created, {generate.data.dependencies_added} dependencies in {generate.data.seconds} s
              </span>
            )}
          </form>
        )}
      </div>
      <ErrorMessage error={apps.error ?? summary.error ?? generate.error} />
      <table aria-label="Applications" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {page?.items.map((a) => (
            <tr key={a.id} className={a.id === selected ? "bg-slate-50" : undefined}>
              <td className="px-2 py-1.5 font-mono text-xs">
                <button type="button" className="underline" aria-label={`Show ${a.application_number}`} onClick={() => setSelected(a.id)}>
                  {a.application_number}
                </button>
              </td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {a.name} · {a.department} · {a.technology} · {a.hosting.replace("_", " ")}
                {a.owner && ` · ${a.owner}`}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={TIER_TONE(a.tier)} label={`tier ${a.tier}`} />
              </td>
              <td className="px-2 py-1.5 text-right text-xs text-slate-600">{a.open_incidents} open incidents</td>
            </tr>
          ))}
        </tbody>
      </table>
      {page && page.total > page.limit && (
        <div className="mt-2 flex items-center gap-2 text-xs text-slate-600">
          <Button size="sm" variant="secondary" disabled={filters.offset === 0} onClick={() => setFilters({ ...filters, offset: Math.max(0, filters.offset - page.limit) })}>
            Previous
          </Button>
          <span>
            {filters.offset + 1}–{Math.min(filters.offset + page.limit, page.total)} of {page.total}
          </span>
          <Button size="sm" variant="secondary" disabled={filters.offset + page.limit >= page.total} onClick={() => setFilters({ ...filters, offset: filters.offset + page.limit })}>
            Next
          </Button>
        </div>
      )}
      {selected && <ApplicationDetailPanel id={selected} />}
    </Panel>
  );
}

function IncidentsPanel() {
  const { can } = useAuth();
  const incidents = useIncidents();
  const open = useOpenIncident();
  const acknowledge = useAcknowledge();
  const resolve = useResolve();
  const close = useCloseIncident();
  const sweep = useSweep();
  const [form, setForm] = useState({ app: "", title: "", impact: "medium", urgency: "medium" });
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [causes, setCauses] = useState<Record<string, string>>({});
  return (
    <Panel title="Incidents" subtitle="Priority comes from impact and urgency: a P1 must be acknowledged in 15 minutes and resolved in 4 hours, a P4 in a day and five days. A P1 closes with a post-incident review by someone other than whoever resolved it.">
      {can("itops:manage") && (
        <form
          aria-label="Report incident"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            open.mutate({ application_number: form.app, title: form.title, impact: form.impact, urgency: form.urgency });
          }}
        >
          <ApplicationSelect label="Incident application" value={form.app} onChange={(v) => setForm({ ...form, app: v })} />
          <input aria-label="What is wrong" placeholder="What is wrong" className={`w-56 ${INPUT}`} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <select aria-label="Impact" className={INPUT} value={form.impact} onChange={(e) => setForm({ ...form, impact: e.target.value })}>
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {humanize(l)} impact
              </option>
            ))}
          </select>
          <select aria-label="Urgency" className={INPUT} value={form.urgency} onChange={(e) => setForm({ ...form, urgency: e.target.value })}>
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {humanize(l)} urgency
              </option>
            ))}
          </select>
          <Button size="sm" type="submit" disabled={!form.app || form.title.trim().length < 5}>
            Report incident
          </Button>
          <Button size="sm" variant="secondary" type="button" onClick={() => sweep.mutate()}>
            Run SLA sweep
          </Button>
          {open.data && (
            <span role="status">
              {open.data.incident_number} opened: P{open.data.priority}
            </span>
          )}
          {sweep.data && <span role="status">{sweep.data.response_breaches + sweep.data.resolution_breaches} breaches marked</span>}
        </form>
      )}
      <ErrorMessage error={incidents.error ?? open.error ?? acknowledge.error ?? resolve.error ?? close.error ?? sweep.error} />
      <table aria-label="Incidents" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {incidents.data?.items.map((i) => (
            <tr key={i.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{i.incident_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                <span className="font-semibold">P{i.priority}</span> · {i.application} · {i.title} · resolve by {when(i.resolve_by)}
                {i.response_breached && <span className="font-semibold text-rose-700"> · response late</span>}
                {i.resolution_breached && <span className="font-semibold text-rose-700"> · resolution late</span>}
                {i.change_number && ` · caused by ${i.change_number}`}
                {i.resolution && ` · ${i.resolution}`}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={INCIDENT_TONE[i.status]} label={i.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex flex-wrap justify-end gap-1">
                  {i.status === "open" && can("itops:manage") && (
                    <Button size="sm" aria-label={`Acknowledge ${i.incident_number}`} onClick={() => acknowledge.mutate(i.id)}>
                      Acknowledge
                    </Button>
                  )}
                  {i.status === "acknowledged" && can("itops:manage") && (
                    <>
                      <input aria-label={`Resolution for ${i.incident_number}`} placeholder="How it was resolved" className={`w-44 ${INPUT}`} value={notes[i.id] ?? ""} onChange={(e) => setNotes({ ...notes, [i.id]: e.target.value })} />
                      <input aria-label={`Caused by change for ${i.incident_number}`} placeholder="CHG- (optional)" className={`w-28 ${INPUT}`} value={causes[i.id] ?? ""} onChange={(e) => setCauses({ ...causes, [i.id]: e.target.value })} />
                      <Button
                        size="sm"
                        aria-label={`Resolve ${i.incident_number}`}
                        disabled={(notes[i.id] ?? "").trim().length < 10}
                        onClick={() => resolve.mutate({ id: i.id, resolution: notes[i.id], change_number: causes[i.id] })}
                      >
                        Resolve
                      </Button>
                    </>
                  )}
                  {i.status === "resolved" && can("itops:approve") && (
                    <>
                      {i.priority === 1 && (
                        <input aria-label={`Review for ${i.incident_number}`} placeholder="Post-incident review" className={`w-52 ${INPUT}`} value={notes[i.id] ?? ""} onChange={(e) => setNotes({ ...notes, [i.id]: e.target.value })} />
                      )}
                      <Button size="sm" variant="secondary" aria-label={`Close ${i.incident_number}`} onClick={() => close.mutate({ id: i.id, review: notes[i.id] })}>
                        Close
                      </Button>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {incidents.data && incidents.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No incidents.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function defaultStart(): string {
  const day = new Date(Date.now() + 3 * 86_400_000);
  day.setUTCHours(22, 0, 0, 0);
  return day.toISOString().slice(0, 16);
}

function ChangesPanel() {
  const { can } = useAuth();
  const changes = useChanges();
  const raise = useRaiseChange();
  const decide = useDecideChange();
  const implement = useImplement();
  const [form, setForm] = useState({ app: "", title: "", kind: "normal", backout: "", start: defaultStart(), hours: "2", incident: "" });
  return (
    <Panel title="Changes" subtitle="Risk comes from the kind, the application's tier and the backout plan. Standard (low-risk) changes are pre-approved; others are approved by someone other than the requester, by an executive for high risk or a tier-1 application. Tier-1 applications are frozen from the 28th to the 1st, except for emergency changes answering a P1 or P2. A failed change opens an incident.">
      {can("itops:manage") && (
        <form
          aria-label="Raise change"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            const start = new Date(`${form.start}:00Z`);
            raise.mutate({
              application_number: form.app,
              title: form.title,
              kind: form.kind,
              backout_plan: form.backout,
              planned_start: start.toISOString(),
              planned_end: new Date(start.getTime() + Number(form.hours) * 3_600_000).toISOString(),
              incident_number: form.kind === "emergency" ? form.incident : undefined,
            });
          }}
        >
          <ApplicationSelect label="Change application" value={form.app} onChange={(v) => setForm({ ...form, app: v })} />
          <input aria-label="What changes" placeholder="What changes" className={`w-48 ${INPUT}`} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <select aria-label="Kind" className={INPUT} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {["standard", "normal", "emergency"].map((k) => (
              <option key={k} value={k}>
                {humanize(k)}
              </option>
            ))}
          </select>
          <input aria-label="Backout plan" placeholder="Backout plan" className={`w-48 ${INPUT}`} value={form.backout} onChange={(e) => setForm({ ...form, backout: e.target.value })} />
          <input aria-label="Starts (UTC)" type="datetime-local" className={INPUT} value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
          <input aria-label="Hours" type="number" min={1} max={24} className={`w-14 ${INPUT}`} value={form.hours} onChange={(e) => setForm({ ...form, hours: e.target.value })} />
          {form.kind === "emergency" && (
            <input aria-label="Incident" placeholder="INC-" className={`w-28 ${INPUT}`} value={form.incident} onChange={(e) => setForm({ ...form, incident: e.target.value })} />
          )}
          <Button size="sm" type="submit" disabled={!form.app || form.title.trim().length < 5}>
            Raise change
          </Button>
          {raise.data && (
            <span role="status">
              {raise.data.change_number} {raise.data.status}: {raise.data.risk} risk
            </span>
          )}
        </form>
      )}
      <ErrorMessage error={changes.error ?? raise.error ?? decide.error ?? implement.error} />
      <table aria-label="Changes" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {changes.data?.items.map((c) => (
            <tr key={c.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{c.change_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {c.application} · {c.title} · {humanize(c.kind)} · {when(c.planned_start)} to {when(c.planned_end)}
                {c.needs_cab && " · executive approval"}
                {c.incident_number && ` · answers ${c.incident_number}`}
              </td>
              <td className="px-2 py-1.5">
                <div className="flex gap-1">
                  <StatusPill compact tone={RISK_TONE[c.risk]} label={`${c.risk} risk`} />
                  <StatusPill compact tone={CHANGE_TONE[c.status]} label={c.status} />
                </div>
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex flex-wrap justify-end gap-1">
                  {c.status === "requested" && can("itops:approve") && (
                    <>
                      <Button size="sm" aria-label={`Approve ${c.change_number}`} onClick={() => decide.mutate({ id: c.id, approve: true })}>
                        Approve
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Reject ${c.change_number}`} onClick={() => decide.mutate({ id: c.id, approve: false })}>
                        Reject
                      </Button>
                    </>
                  )}
                  {c.status === "approved" && can("itops:manage") && (
                    <>
                      <Button size="sm" aria-label={`Implemented ${c.change_number}`} onClick={() => implement.mutate({ id: c.id, success: true })}>
                        Implemented
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Failed ${c.change_number}`} onClick={() => implement.mutate({ id: c.id, success: false })}>
                        Failed
                      </Button>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {changes.data && changes.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No changes.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

/** IT operations (Phase 59): the application catalogue, incidents and change management. */
export function ItopsPage() {
  const summary = useItopsSummary();
  return (
    <>
      <PageHeader title="IT Operations" description="The bank's applications by criticality, incidents against them with response and resolution targets, and changes risk-rated, approved by a second person and kept out of the month-end freeze." />
      {summary.data && (
        <dl aria-label="IT operations summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {(
            [
              ["Applications", summary.data.applications],
              ["Open incidents", summary.data.incidents_open],
              ["Open P1s", summary.data.p1_open],
              ["Past resolution target", summary.data.incidents_breached],
              ["Incidents to close", summary.data.incidents_to_close],
              ["Changes to approve", summary.data.changes_to_approve],
              ["Changes scheduled", summary.data.changes_scheduled],
              ["Failed changes (30 days)", summary.data.changes_failed_30d],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {summary.data?.frozen_now && (
        <p role="note" className="mb-4 rounded-md bg-amber-50 p-2 text-sm text-amber-900">
          Month-end freeze: only emergency changes go into tier-1 applications.
        </p>
      )}
      <div className="flex flex-col gap-6">
        <IncidentsPanel />
        <ChangesPanel />
        <ApplicationsPanel />
        <OutagesPanel />
      </div>
    </>
  );
}
