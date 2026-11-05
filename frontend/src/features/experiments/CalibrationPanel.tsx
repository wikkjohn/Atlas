import { Upload } from "lucide-react";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { useCalibrations, useCreateCalibration } from "@/services/experiments";
import type { Estimate, ReviewerCalibration, ReviewObservation } from "@/types/experiments";

const minutes = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v.toFixed(1)} min`);
const share = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
const plain = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toFixed(2));

function Row({ label, fit, assumed, format }: { label: string; fit: Estimate | null | undefined; assumed: number | null | undefined; format: (v: number | null | undefined) => string }) {
  return (
    <tr>
      <td className="pr-4 py-1">{label}</td>
      <td className="pr-4 py-1 text-right tabular-nums">{fit ? format(fit.estimate) : "not fitted"}</td>
      <td className="pr-4 py-1 text-right tabular-nums text-slate-500">
        {fit && fit.low !== null ? `${format(fit.low)} – ${format(fit.high)}` : "—"}
      </td>
      <td className="pr-4 py-1 text-right tabular-nums text-slate-500">{format(assumed)}</td>
    </tr>
  );
}

function CalibrationView({ c }: { c: ReviewerCalibration }) {
  const r = c.fitted.reviewer;
  const ai = c.fitted.ai_assistance;
  const a = c.assumption;
  return (
    <section aria-label={`Calibration #${c.calibration_number}`} className="space-y-2 rounded-xl border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold text-slate-900">
          #{c.calibration_number} {c.scenario_id} · {c.step_id}
        </span>
        <StatusPill tone={c.status === "active" ? "good" : "neutral"} label={c.status === "active" ? "Active" : "Superseded"} />
        <span className="text-xs text-slate-500">
          {c.observation_count} reviews ({c.fitted.unassisted} without AI, {c.fitted.assisted} with) · {c.source}
        </span>
      </div>
      <table aria-label={`Fitted against assumed, calibration ${c.calibration_number}`} className="text-xs">
        <thead className="text-left text-slate-500">
          <tr>
            <th className="pr-4 py-1 font-medium">Parameter</th>
            <th className="pr-4 py-1 text-right font-medium">Fitted</th>
            <th className="pr-4 py-1 text-right font-medium">{Math.round(c.fitted.confidence * 100)}% interval</th>
            <th className="pr-4 py-1 text-right font-medium">Assumed</th>
          </tr>
        </thead>
        <tbody>
          <Row label="Mean review time" fit={r.mean_minutes} assumed={a.reviewer?.mean_minutes} format={minutes} />
          <Row label="Spread (sigma)" fit={r.sigma} assumed={a.reviewer?.sigma} format={plain} />
          <Row label="Accuracy, should approve" fit={r.accuracy} assumed={a.reviewer?.accuracy} format={share} />
          <Row
            label="Accuracy, should reject"
            fit={r.accuracy_should_reject}
            assumed={a.reviewer?.accuracy_should_reject ?? a.reviewer?.accuracy}
            format={share}
          />
          {a.ai_assistance && (
            <>
              <Row label="Time with AI advice (share)" fit={ai?.review_time_factor} assumed={a.ai_assistance.review_time_factor} format={plain} />
              <Row label="Accuracy when the AI is right" fit={ai?.accuracy_when_ai_correct} assumed={a.ai_assistance.accuracy_when_ai_correct} format={share} />
              <Row label="Accuracy when the AI is wrong" fit={ai?.accuracy_when_ai_wrong} assumed={a.ai_assistance.accuracy_when_ai_wrong} format={share} />
            </>
          )}
        </tbody>
      </table>
      {c.fitted.notes.length > 0 && (
        <ul className="list-disc pl-5 text-[11px] text-amber-800">
          {c.fitted.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** "minutes,truth,decision,ai_recommendation" lines (a header line is skipped) or a JSON array. */
export function parseObservations(text: string): ReviewObservation[] {
  const trimmed = text.trim();
  if (trimmed.startsWith("[")) return JSON.parse(trimmed) as ReviewObservation[];
  const decisions = new Set(["approve", "reject"]);
  return trimmed
    .split(/\r?\n/)
    .map((line) => line.split(",").map((cell) => cell.trim()))
    .filter((cells) => cells.length >= 3 && !Number.isNaN(Number(cells[0])))
    .map(([m, truth, decision, ai]) => {
      if (!decisions.has(truth) || !decisions.has(decision)) throw new Error(`Not approve/reject: ${truth}, ${decision}`);
      // An empty fourth cell means no advice was shown; anything else must be a recommendation.
      if (ai && !decisions.has(ai)) throw new Error(`Not an AI recommendation (approve/reject or empty): ${ai}`);
      return {
        minutes: Number(m),
        truth: truth as "approve" | "reject",
        decision: decision as "approve" | "reject",
        ai_recommendation: ai && decisions.has(ai) ? (ai as "approve" | "reject") : null,
      };
    });
}

function UploadDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateCalibration();
  const [scenarioId, setScenarioId] = useState("retail-onboarding");
  const [stepId, setStepId] = useState("account_approval");
  const [source, setSource] = useState("");
  const [text, setText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setParseError(null);
    let observations: ReviewObservation[];
    try {
      observations = parseObservations(text);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "The reviews could not be read.");
      return;
    }
    if (source.trim().length < 5) {
      setParseError("Say where the reviews come from.");
      return;
    }
    create.mutate({ scenario_id: scenarioId, step_id: stepId, source: source.trim(), observations }, { onSuccess: onClose });
  };
  return (
    <Modal title="Calibrate reviewers" onClose={onClose} wide>
      <form id="calibrate" aria-label="Calibrate reviewers" onSubmit={submit} className="space-y-3">
        <p className="text-xs text-slate-500">
          Observed reviews of one review step, one per line: minutes, the right decision, the reviewer's decision, and the AI
          recommendation shown (empty if none) — e.g. <span className="font-mono">14.5,approve,approve,reject</span>. At least 30
          reviews without AI advice. The fit becomes the step's active calibration; new runs simulate it.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Scenario">
            {(p) => <input {...p} className={inputClass} value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} />}
          </Field>
          <Field label="Review step">
            {(p) => <input {...p} className={inputClass} value={stepId} onChange={(e) => setStepId(e.target.value)} />}
          </Field>
          <Field label="Source">
            {(p) => <input {...p} className={inputClass} value={source} onChange={(e) => setSource(e.target.value)} />}
          </Field>
        </div>
        <Field label="Reviews">
          {(p) => <textarea {...p} rows={8} className={`${inputClass} font-mono text-xs`} value={text} onChange={(e) => setText(e.target.value)} />}
        </Field>
        {parseError && <p className="text-xs text-rose-700">{parseError}</p>}
      </form>
      <ErrorMessage error={create.error} className="mt-3" />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" form="calibrate" disabled={create.isPending}>
          <Upload aria-hidden className="h-4 w-4" /> Fit and activate
        </Button>
      </div>
    </Modal>
  );
}

export function CalibrationPanel() {
  const { can } = useAuth();
  const calibrations = useCalibrations();
  const [uploading, setUploading] = useState(false);
  const active = (calibrations.data ?? []).filter((c) => c.status === "active");
  const older = (calibrations.data ?? []).filter((c) => c.status !== "active");
  return (
    <Panel
      title="Reviewer calibration"
      subtitle="Review times and accuracy fitted from observed reviews, with intervals, instead of stated assumptions"
      actions={
        can("experiments:run") ? (
          <Button size="sm" onClick={() => setUploading(true)}>
            <Upload aria-hidden className="h-4 w-4" /> Calibrate reviewers
          </Button>
        ) : undefined
      }
    >
      <ErrorMessage error={calibrations.error} />
      {calibrations.data && calibrations.data.length === 0 && (
        <p className="text-sm text-slate-500">No calibration yet: every scenario simulates its stated assumptions.</p>
      )}
      <div className="space-y-3">
        {active.map((c) => (
          <CalibrationView key={c.id} c={c} />
        ))}
        {older.length > 0 && (
          <details className="text-xs text-slate-600">
            <summary className="cursor-pointer">{older.length} superseded calibration(s)</summary>
            <div className="mt-2 space-y-2">
              {older.map((c) => (
                <CalibrationView key={c.id} c={c} />
              ))}
            </div>
          </details>
        )}
      </div>
      {uploading && <UploadDialog onClose={() => setUploading(false)} />}
    </Panel>
  );
}
