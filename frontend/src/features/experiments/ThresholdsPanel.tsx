import { Check, Scale, X } from "lucide-react";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { useDecideThresholds, useProposeThresholds, useScenarioThresholds } from "@/services/experiments";
import { humanize } from "@/services/format";
import {
  RISK_TIERS,
  type RiskTier,
  type ScenarioThresholdRow,
  type SuccessThresholds,
  type ThresholdOverview,
  type ThresholdsSource,
  type ThresholdVersion,
} from "@/types/experiments";

export const TIER_TONE: Record<RiskTier, Tone> = { critical: "bad", high: "warn", medium: "neutral", low: "good" };

export const LIMIT_FIELDS: { key: keyof SuccessThresholds; label: string; short: string }[] = [
  { key: "max_false_approval_rate", label: "Maximum false approval rate", short: "False approvals" },
  { key: "max_false_rejection_rate", label: "Maximum false rejection rate", short: "False rejections" },
  { key: "max_accuracy_drop", label: "Maximum accuracy drop", short: "Accuracy drop" },
  { key: "max_error_rate", label: "Maximum error rate", short: "Errors" },
  { key: "min_improvement", label: "Minimum improvement (time, labour or cost)", short: "Improvement" },
];

const share = (v: number) => `${(v * 100).toFixed(1).replace(/\.0$/, "")}%`;

/** Where an experiment's thresholds came from, in words. */
export function sourceLabel(source: ThresholdsSource | undefined): string {
  switch (source?.source) {
    case "scenario":
      return `Approved for ${source.scenario_id}, version ${source.version} (${source.risk_tier} risk)`;
    case "tier_default":
      return `Defaults for ${source.scenario_id}'s risk tier (${source.risk_tier})`;
    case "request":
      return "Set for this experiment";
    case "scenario_per_cell":
      return "Each cell's own scenario thresholds";
    default:
      return "The bank's defaults (before Phase 80)";
  }
}

function ProposeDialog({
  row,
  overview,
  onClose,
}: {
  row: ScenarioThresholdRow;
  overview: ThresholdOverview;
  onClose: () => void;
}) {
  const propose = useProposeThresholds();
  const [tier, setTier] = useState<RiskTier>(row.risk_tier);
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(row.thresholds).map(([k, v]) => [k, String(v)])),
  );
  const [rationale, setRationale] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const errors: Record<string, string | null> = {
    rationale: rationale.trim().length >= 20 ? null : "Say why, in at least 20 characters.",
    ...Object.fromEntries(
      LIMIT_FIELDS.map((f) => {
        const v = Number(values[f.key]);
        return [f.key, values[f.key]?.trim() !== "" && Number.isFinite(v) && v >= 0 && v <= 1 ? null : "A share between 0 and 1."];
      }),
    ),
  };
  const valid = Object.values(errors).every((e) => e === null);
  const chooseTier = (next: RiskTier) => {
    setTier(next);
    const { description: _description, ...defaults } = overview.tiers[next];
    setValues(Object.fromEntries(Object.entries(defaults).map(([k, v]) => [k, String(v)])));
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!valid) return;
    propose.mutate(
      {
        scenario_id: row.scenario_id,
        risk_tier: tier,
        thresholds: Object.fromEntries(Object.entries(values).map(([k, v]) => [k, Number(v)])) as unknown as SuccessThresholds,
        rationale: rationale.trim(),
      },
      { onSuccess: onClose },
    );
  };
  return (
    <Modal title={`Propose thresholds: ${row.name}`} onClose={onClose}>
      <form id="propose-thresholds" aria-label="Propose thresholds" onSubmit={submit} className="space-y-3">
        <p className="text-xs text-slate-500">
          A risk approver — someone other than you — decides. Until then, experiments keep the thresholds in force.
        </p>
        <Field label="Risk tier" hint={overview.tiers[tier].description}>
          {(p) => (
            <select {...p} className={inputClass} value={tier} onChange={(e) => chooseTier(e.target.value as RiskTier)}>
              {RISK_TIERS.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          {LIMIT_FIELDS.map((f) => (
            <Field key={f.key} label={f.label} error={submitted ? errors[f.key] : null}>
              {(p) => (
                <input
                  {...p}
                  type="number"
                  step="0.005"
                  className={inputClass}
                  value={values[f.key]}
                  onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                />
              )}
            </Field>
          ))}
        </div>
        <Field label="Rationale" error={submitted ? errors.rationale : null}>
          {(p) => <textarea {...p} rows={3} className={inputClass} value={rationale} onChange={(e) => setRationale(e.target.value)} />}
        </Field>
      </form>
      <ErrorMessage error={propose.error} className="mt-3" />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" form="propose-thresholds" disabled={propose.isPending}>
          Submit proposal
        </Button>
      </div>
    </Modal>
  );
}

function PendingDecision({ pending }: { pending: ThresholdVersion }) {
  const { can, user } = useAuth();
  const decide = useDecideThresholds();
  const [note, setNote] = useState("");
  const mine = pending.proposed_by_username === user?.username;
  return (
    <div className="space-y-1">
      <p className="text-xs text-amber-800">
        v{pending.version} ({pending.risk_tier}) proposed by {pending.proposed_by_username}: {pending.rationale}
      </p>
      {can("risk:approve") && !mine && (
        <div className="flex flex-wrap items-center gap-1">
          <input
            aria-label={`Decision note for version ${pending.version}`}
            className={`${inputClass} h-7 w-44 text-xs`}
            placeholder="Note (needed to reject)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <Button size="sm" disabled={decide.isPending} onClick={() => decide.mutate({ id: pending.id, decision: "approve", note })}>
            <Check aria-hidden className="h-3.5 w-3.5" /> Approve
          </Button>
          <Button size="sm" variant="secondary" disabled={decide.isPending} onClick={() => decide.mutate({ id: pending.id, decision: "reject", note })}>
            <X aria-hidden className="h-3.5 w-3.5" /> Reject
          </Button>
        </div>
      )}
      {mine && <p className="text-[11px] text-slate-500">Your proposal: someone else decides.</p>}
      <ErrorMessage error={decide.error} />
    </div>
  );
}

export function ThresholdsPanel() {
  const { can } = useAuth();
  const overview = useScenarioThresholds();
  const [proposing, setProposing] = useState<ScenarioThresholdRow | null>(null);
  const data = overview.data;
  return (
    <Panel
      title="Scenario thresholds"
      subtitle="What counts as success depends on the risk: each scenario has a risk tier, and may have approved thresholds of its own. Values are illustrative."
    >
      <ErrorMessage error={overview.error} />
      {data && (
        <div className="space-y-3">
          <ul aria-label="Risk tiers" className="grid gap-2 text-xs sm:grid-cols-4">
            {RISK_TIERS.map((t) => (
              <li key={t} className="rounded-lg border border-slate-200 p-2">
                <StatusPill tone={TIER_TONE[t]} label={humanize(t)} />
                <p className="mt-1 text-slate-600">{data.tiers[t].description}</p>
                <p className="mt-1 text-slate-500">
                  False approvals ≤ {share(data.tiers[t].max_false_approval_rate)}, false rejections ≤{" "}
                  {share(data.tiers[t].max_false_rejection_rate)}
                </p>
              </li>
            ))}
          </ul>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table aria-label="Thresholds by scenario" className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="px-3 py-2">Scenario</th>
                  <th className="px-3 py-2">Tier</th>
                  {LIMIT_FIELDS.slice(0, 4).map((f) => (
                    <th key={f.key} className="px-3 py-2 text-right">
                      {f.short}
                    </th>
                  ))}
                  <th className="px-3 py-2">In force</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.scenarios.map((r) => (
                  <tr key={r.scenario_id} className="align-top">
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-900">{r.name}</div>
                      <div className="text-xs text-slate-500">{r.rationale}</div>
                      {r.pending && <PendingDecision pending={r.pending} />}
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill tone={TIER_TONE[r.risk_tier]} label={humanize(r.risk_tier)} />
                    </td>
                    {LIMIT_FIELDS.slice(0, 4).map((f) => (
                      <td key={f.key} className="px-3 py-2 text-right text-xs">
                        {share(r.thresholds[f.key])}
                      </td>
                    ))}
                    <td className="px-3 py-2 text-xs text-slate-600">
                      {r.source === "scenario" ? `Approved v${r.version}` : "Tier default"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {can("experiments:run") && !r.pending && (
                        <Button size="sm" variant="secondary" onClick={() => setProposing(r)}>
                          <Scale aria-hidden className="h-3.5 w-3.5" /> Propose
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {proposing && data && <ProposeDialog row={proposing} overview={data} onClose={() => setProposing(null)} />}
    </Panel>
  );
}
