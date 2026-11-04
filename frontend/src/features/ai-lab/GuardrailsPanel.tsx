import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { humanize } from "@/services/format";
import { useToolBias, useToolDrift, useToolRuns, useVerifyAudit } from "@/services/aiTools";
import type { BiasFinding, DriftStatus, ToolRun } from "@/types/aiTools";

const FINDING_TONE: Record<BiasFinding, Tone> = {
  disparity: "bad",
  no_disparity: "good",
  insufficient_data: "neutral",
};
const DRIFT_TONE: Record<DriftStatus, Tone> = {
  stable: "good",
  moderate: "warn",
  significant: "bad",
  no_data: "neutral",
};

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)} %`);
const num = (v: number | null | undefined, digits = 3) => (v == null ? "—" : v.toFixed(digits));
const pValue = (v: number | null | undefined) => (v == null ? "—" : v < 0.0001 ? "< 0.0001" : v.toFixed(4));
const runLabel = (r: ToolRun) => `Run #${r.run_number} · ${humanize(r.mode)} · ${r.calls} calls`;

function RunSelect({
  label,
  runs,
  value,
  onChange,
  allowAll,
}: {
  label: string;
  runs: ToolRun[];
  value: string;
  onChange: (v: string) => void;
  allowAll?: boolean;
}) {
  return (
    <Field label={label}>
      {(props) => (
        <select {...props} className={inputClass} value={value} onChange={(e) => onChange(e.target.value)}>
          {allowAll && <option value="">All recorded calls</option>}
          {!allowAll && <option value="">Choose a run</option>}
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              {runLabel(r)}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

function BiasSection({ id, runs }: { id: string; runs: ToolRun[] }) {
  const [runId, setRunId] = useState("");
  const bias = useToolBias(id, runId || null);
  const b = bias.data;
  return (
    <section aria-label="Bias across segments" className="space-y-2 rounded-lg border border-slate-200 p-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold text-slate-900">Bias across segments</h4>
          <p className="text-xs text-slate-500">
            Segments come from the tool's inputs. With ground truth the test is equal opportunity (how often cases
            that should be approved are recommended for rejection); otherwise approval rates and the four-fifths rule.
          </p>
        </div>
        <div className="w-72">
          <RunSelect label="Calls" runs={runs} value={runId} onChange={setRunId} allowAll />
        </div>
      </div>
      <ErrorMessage error={bias.error} />
      {b && (
        <>
          <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <StatusPill
              tone={b.status === "flagged" ? "bad" : b.status === "clear" ? "good" : "neutral"}
              label={humanize(b.status)}
            />
            {b.recommendations} recommendations, {b.with_ground_truth} with ground truth; groups under {b.min_group}{" "}
            cases are left out.
          </p>
          {b.attributes.length === 0 && (
            <p className="text-sm text-slate-500">No segment attributes in the recorded inputs.</p>
          )}
          {b.attributes.map((a) => (
            <div key={a.attribute} className="overflow-x-auto rounded-lg border border-slate-100">
              <table aria-label={`Bias by ${a.attribute}`} className="min-w-full text-xs">
                <caption className="px-3 py-2 text-left">
                  <span className="font-semibold text-slate-800 capitalize">{a.attribute}</span>{" "}
                  <StatusPill tone={FINDING_TONE[a.finding]} label={humanize(a.finding)} />{" "}
                  <span className="text-slate-500">
                    {a.test === "equal_opportunity" ? "Equal opportunity" : "Demographic parity"} · p (Holm){" "}
                    {pValue(a.p_adjusted)} · approval ratio {num(a.approval_ratio)}
                    {a.four_fifths_rule === false && " (below four-fifths)"}
                    {a.false_rejection_gap != null && ` · false-rejection gap ${pct(a.false_rejection_gap)}`}
                    {a.excluded_groups.length > 0 && ` · left out: ${a.excluded_groups.join(", ")}`}
                  </span>
                </caption>
                <thead className="bg-slate-50 text-left font-medium text-slate-500">
                  <tr>
                    <th className="px-3 py-1.5">Group</th>
                    <th className="px-3 py-1.5 text-right">Cases</th>
                    <th className="px-3 py-1.5 text-right">Approve</th>
                    <th className="px-3 py-1.5 text-right">Reject</th>
                    <th className="px-3 py-1.5 text-right">Escalate</th>
                    <th className="px-3 py-1.5 text-right">False rejections</th>
                    <th className="px-3 py-1.5 text-right">False approvals</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {a.groups.map((g) => (
                    <tr key={g.group}>
                      <td className="px-3 py-1.5 font-medium">{g.group}</td>
                      <td className="px-3 py-1.5 text-right">{g.n}</td>
                      <td className="px-3 py-1.5 text-right">{pct(g.approve_rate)}</td>
                      <td className="px-3 py-1.5 text-right">{pct(g.reject_rate)}</td>
                      <td className="px-3 py-1.5 text-right">{pct(g.escalate_rate)}</td>
                      <td className="px-3 py-1.5 text-right">
                        {pct(g.false_rejection_rate)}
                        {g.should_approve > 0 && <span className="text-slate-400"> of {g.should_approve}</span>}
                      </td>
                      <td className="px-3 py-1.5 text-right">{pct(g.false_approval_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          <p className="text-[11px] text-slate-500">{b.method}</p>
        </>
      )}
    </section>
  );
}

function DriftSection({ id, runs }: { id: string; runs: ToolRun[] }) {
  // Runs come newest first: compare the newest against the oldest by default.
  const [reference, setReference] = useState(runs.length >= 2 ? runs[runs.length - 1].id : "");
  const [current, setCurrent] = useState(runs.length >= 2 ? runs[0].id : "");
  const drift = useToolDrift(id, reference || null, current || null);
  const d = reference && current && reference !== current ? drift.data : undefined;
  return (
    <section aria-label="Drift" className="space-y-2 rounded-lg border border-slate-200 p-3">
      <div>
        <h4 className="text-sm font-semibold text-slate-900">Drift</h4>
        <p className="text-xs text-slate-500">
          How the tool's answers and inputs moved between two simulation runs: Population Stability Index, with a
          chi-square test so that a shift sampling noise explains counts as stable.
        </p>
      </div>
      {runs.length < 2 ? (
        <p className="text-sm text-slate-500">Drift needs at least two simulation runs that called the tool.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <RunSelect label="Reference run" runs={runs} value={reference} onChange={setReference} />
          <RunSelect label="Current run" runs={runs} value={current} onChange={setCurrent} />
        </div>
      )}
      {reference && reference === current && <p className="text-sm text-slate-500">Choose two different runs.</p>}
      <ErrorMessage error={drift.error} />
      {d && (
        <>
          <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <StatusPill tone={DRIFT_TONE[d.status]} label={`Overall: ${humanize(d.status)}`} />
            {d.reference.calls} reference calls, {d.current.calls} current calls
          </p>
          <div className="overflow-x-auto rounded-lg border border-slate-100">
            <table aria-label="Drift measures" className="min-w-full text-xs">
              <thead className="bg-slate-50 text-left font-medium text-slate-500">
                <tr>
                  <th className="px-3 py-1.5">Measure</th>
                  <th className="px-3 py-1.5 text-right">Reference</th>
                  <th className="px-3 py-1.5 text-right">Current</th>
                  <th className="px-3 py-1.5 text-right">PSI</th>
                  <th className="px-3 py-1.5 text-right">p</th>
                  <th className="px-3 py-1.5">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr>
                  <td className="px-3 py-1.5 font-medium">Recommendations</td>
                  <td className="px-3 py-1.5 text-right">
                    {Object.entries(d.recommendations.shares)
                      .map(([k, v]) => `${humanize(k)} ${pct(v.reference)}`)
                      .join(", ")}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    {Object.entries(d.recommendations.shares)
                      .map(([k, v]) => `${humanize(k)} ${pct(v.current)}`)
                      .join(", ")}
                  </td>
                  <td className="px-3 py-1.5 text-right">{num(d.recommendations.psi)}</td>
                  <td className="px-3 py-1.5 text-right">{pValue(d.recommendations.p_value)}</td>
                  <td className="px-3 py-1.5">
                    <StatusPill tone={DRIFT_TONE[d.recommendations.status]} label={humanize(d.recommendations.status)} />
                  </td>
                </tr>
                <tr>
                  <td className="px-3 py-1.5 font-medium">Mean confidence</td>
                  <td className="px-3 py-1.5 text-right">{num(d.confidence.reference_mean)}</td>
                  <td className="px-3 py-1.5 text-right">{num(d.confidence.current_mean)}</td>
                  <td className="px-3 py-1.5 text-right">—</td>
                  <td className="px-3 py-1.5 text-right">{pValue(d.confidence.p_value)}</td>
                  <td className="px-3 py-1.5" />
                </tr>
                <tr>
                  <td className="px-3 py-1.5 font-medium">Error rate</td>
                  <td className="px-3 py-1.5 text-right">{pct(d.error_rate.reference)}</td>
                  <td className="px-3 py-1.5 text-right">{pct(d.error_rate.current)}</td>
                  <td className="px-3 py-1.5 text-right">—</td>
                  <td className="px-3 py-1.5 text-right">{pValue(d.error_rate.p_value)}</td>
                  <td className="px-3 py-1.5" />
                </tr>
                {d.inputs.map((i) => (
                  <tr key={i.attribute}>
                    <td className="px-3 py-1.5 font-medium">
                      Inputs: <span className="capitalize">{i.attribute}</span>
                    </td>
                    <td className="px-3 py-1.5 text-right">—</td>
                    <td className="px-3 py-1.5 text-right">—</td>
                    <td className="px-3 py-1.5 text-right">{num(i.psi)}</td>
                    <td className="px-3 py-1.5 text-right">{pValue(i.p_value)}</td>
                    <td className="px-3 py-1.5">
                      <StatusPill tone={DRIFT_TONE[i.status]} label={humanize(i.status)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-slate-500">{d.method}</p>
        </>
      )}
    </section>
  );
}

function AuditSection({ id }: { id: string }) {
  const verify = useVerifyAudit(id);
  const v = verify.data;
  return (
    <section aria-label="Audit" className="space-y-2 rounded-lg border border-slate-200 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold text-slate-900">Audit</h4>
          <p className="text-xs text-slate-500">
            Every call is stored with a SHA-256 hash of its record; hosted-model calls also keep the exact prompt and
            answer. Verifying recomputes each hash and lists the records that no longer match.
          </p>
        </div>
        <Button variant="secondary" size="sm" disabled={verify.isPending} onClick={() => verify.mutate()}>
          <ShieldCheck aria-hidden className="h-4 w-4" /> Verify records
        </Button>
      </div>
      <ErrorMessage error={verify.error} />
      {v && (
        <div className="space-y-1 text-xs text-slate-600">
          <p className="flex flex-wrap items-center gap-2">
            <StatusPill tone={v.status === "intact" ? "good" : "bad"} label={humanize(v.status)} />
            {v.valid} of {v.checked} records match their hash
            {v.unhashed > 0 && `; ${v.unhashed} recorded before hashing began`}.
          </p>
          {v.mismatched_ids.length > 0 && (
            <ul aria-label="Altered records" className="font-mono text-[11px] text-red-700">
              {v.mismatched_ids.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

export function GuardrailsPanel({ id }: { id: string }) {
  const runs = useToolRuns(id);
  return (
    <section aria-label="Guardrails" className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-900">Guardrails</h3>
      <ErrorMessage error={runs.error} />
      {runs.data && (
        <>
          <BiasSection id={id} runs={runs.data} />
          <DriftSection key={runs.data.map((r) => r.id).join()} id={id} runs={runs.data} />
        </>
      )}
      <AuditSection id={id} />
    </section>
  );
}
