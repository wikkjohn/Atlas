import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { ApiError, newIdempotencyKey } from "@/services/api";
import { humanize } from "@/services/format";
import {
  exportDefinition,
  useImportDefinition,
  useLibraryHandlers,
  useStartExecution,
  useValidateDefinition,
} from "@/services/workflows";
import type {
  DefinitionProblem,
  HandlerEffect,
  JsonSchema,
  JsonSchemaProperty,
  ValidationReport,
} from "@/types/workflows";

const EFFECT_LABEL: Record<HandlerEffect, string> = {
  none: "No side effects",
  reads: "Reads records",
  writes: "Writes records",
  moves_money: "Moves money",
  advisory: "AI advice",
};
const EFFECT_STYLE: Record<HandlerEffect, string> = {
  none: "bg-slate-100 text-slate-600",
  reads: "bg-slate-100 text-slate-700",
  writes: "bg-amber-50 text-amber-800",
  moves_money: "bg-rose-50 text-rose-800",
  advisory: "bg-violet-50 text-violet-800",
};

export function EffectBadge({ effect }: { effect: HandlerEffect }) {
  if (effect === "none") return null;
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${EFFECT_STYLE[effect]}`}>{EFFECT_LABEL[effect]}</span>;
}

/** Which steps change records or move money, grouped by effect. */
function EffectsSummary({ effects }: { effects: Record<string, HandlerEffect> }) {
  const order: HandlerEffect[] = ["moves_money", "writes", "advisory", "reads"];
  const groups = order
    .map((effect) => [effect, Object.keys(effects).filter((step) => effects[step] === effect)] as const)
    .filter(([, list]) => list.length > 0);
  if (groups.length === 0) return null;
  return (
    <ul aria-label="Effects" className="space-y-1 text-xs text-slate-700">
      {groups.map(([effect, list]) => (
        <li key={effect} className="flex flex-wrap items-center gap-1.5">
          <EffectBadge effect={effect} /> <span className="font-mono">{list.join(", ")}</span>
        </li>
      ))}
    </ul>
  );
}

function Problems({ title, items, tone }: { title: string; items: DefinitionProblem[]; tone: "bad" | "warn" }) {
  if (items.length === 0) return null;
  const color = tone === "bad" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-amber-200 bg-amber-50 text-amber-900";
  return (
    <div className={`rounded-lg border p-3 text-sm ${color}`}>
      <p className="font-medium">
        {title} ({items.length})
      </p>
      <ul aria-label={title} className="mt-1 space-y-1 text-xs">
        {items.map((p) => (
          <li key={`${p.location}:${p.code}:${p.message}`}>
            <span className="font-mono">{p.location}</span> — {p.message}{" "}
            <span className="font-mono opacity-70">[{p.code}]</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The problems an import refusal (422 definition_invalid) carries, as a report. */
function refusalReport(error: unknown): ValidationReport | null {
  if (!(error instanceof ApiError) || error.code !== "definition_invalid") return null;
  const details = error.details as { errors: DefinitionProblem[]; warnings: DefinitionProblem[] };
  return { valid: false, workflow_id: null, version: null, content_hash: null, existing: null, ...details };
}

/** Paste (or start from an existing workflow's export), validate, then import. */
export function ImportDefinitionDialog({
  startFrom,
  onClose,
  onImported,
}: {
  startFrom: string | null;
  onClose: () => void;
  onImported: (workflowId: string) => void;
}) {
  const [text, setText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const validate = useValidateDefinition();
  const importer = useImportDefinition();
  const handlers = useLibraryHandlers();

  const parsed = (): unknown => {
    try {
      setParseError(null);
      return JSON.parse(text);
    } catch (cause) {
      setParseError(`Not valid JSON: ${(cause as Error).message}`);
      return undefined;
    }
  };
  const onValidate = () => {
    const definition = parsed();
    if (definition !== undefined) validate.mutate(definition, { onSuccess: setReport });
  };
  const onImport = () => {
    const definition = parsed();
    if (definition === undefined) return;
    importer.mutate(definition, {
      onSuccess: (result) => onImported(result.definition.workflow_id),
      onError: (error) => setReport(refusalReport(error)),
    });
  };
  const loadFrom = async (workflowId: string) => {
    const document = await exportDefinition(workflowId);
    setText(JSON.stringify({ ...document, version: Number(document.version) + 1 }, null, 2));
    setReport(null);
  };

  return (
    <Modal
      wide
      title="Import a workflow definition"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="secondary" disabled={!text || validate.isPending} onClick={onValidate}>
            {validate.isPending ? "Validating…" : "Validate"}
          </Button>
          <Button disabled={!text || importer.isPending} onClick={onImport}>
            {importer.isPending ? "Importing…" : "Import"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-slate-600">
          A definition is JSON: its steps, routes, approval policies and an input schema. Service tasks use handlers from
          the library. Every problem is listed before anything is stored; versions are immutable once imported.
        </p>
        {startFrom && (
          <Button size="sm" variant="secondary" onClick={() => void loadFrom(startFrom)}>
            Start from {startFrom} (as its next version)
          </Button>
        )}
        <Field label="Definition (JSON)">
          {(p) => (
            <textarea
              {...p}
              className={`${inputClass} h-72 font-mono text-xs`}
              spellCheck={false}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setReport(null);
              }}
            />
          )}
        </Field>
        {parseError && (
          <p role="alert" className="text-sm text-rose-700">
            {parseError}
          </p>
        )}
        {report?.valid && (
          <p className="flex items-center gap-1.5 text-sm text-emerald-800">
            <CheckCircle2 aria-hidden className="h-4 w-4" />
            {report.workflow_id} v{report.version} is valid
            {report.existing === "identical" ? " and already stored unchanged." : " and can be imported."}
          </p>
        )}
        {report?.valid && report.effects && <EffectsSummary effects={report.effects} />}
        {report && <Problems title="Errors" items={report.errors} tone="bad" />}
        {report && <Problems title="Warnings" items={report.warnings} tone="warn" />}
        <ErrorMessage error={validate.error ?? (refusalReport(importer.error) ? null : importer.error)} />
        {handlers.data && (
          <details className="text-xs text-slate-600">
            <summary className="cursor-pointer font-medium text-slate-700">Handler library ({handlers.data.length})</summary>
            <ul className="mt-2 space-y-1">
              {handlers.data.map((h) => (
                <li key={h.name}>
                  <span className="font-mono">{h.name}</span> <EffectBadge effect={h.effect} />
                  {h.requires_approval && <span className="text-rose-700"> (approval required)</span>} — {h.summary} Params:{" "}
                  <span className="font-mono">
                    {Object.keys((h.params_schema.properties as Record<string, unknown>) ?? {}).join(", ")}
                  </span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Modal>
  );
}

type Value = string | boolean;

function initialValue(property: JsonSchemaProperty): Value {
  return property.type === "boolean" ? false : "";
}

function cast(property: JsonSchemaProperty, value: Value): unknown {
  if (property.type === "boolean") return value;
  if (property.type === "integer" || property.type === "number") return value === "" ? undefined : Number(value);
  if (property.enum && typeof property.enum[0] === "number") return Number(value);
  return value === "" ? undefined : value;
}

/** A start form generated from a stored definition's input schema. */
export function StartFromSchemaDialog({
  workflowId,
  name,
  schema,
  onClose,
  onStarted,
}: {
  workflowId: string;
  name: string;
  schema: JsonSchema;
  onClose: () => void;
  onStarted: (id: string) => void;
}) {
  const start = useStartExecution(workflowId);
  const [key] = useState(newIdempotencyKey);
  const properties = Object.entries(schema.properties ?? {});
  const required = new Set(schema.required ?? []);
  const [values, setValues] = useState<Record<string, Value>>(() =>
    Object.fromEntries(properties.map(([k, p]) => [k, initialValue(p)])),
  );
  const unsupported = properties.filter(([, p]) => !p.type && !p.enum).map(([k]) => k);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const input: Record<string, unknown> = {};
    for (const [k, p] of properties) {
      const v = cast(p, values[k]);
      if (v !== undefined) input[k] = v;
    }
    start.mutate({ idempotencyKey: key, input }, { onSuccess: (execution) => onStarted(execution.id) });
  };

  return (
    <Modal
      wide
      title={`Start ${name} (${workflowId})`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="schema-start" disabled={start.isPending}>
            {start.isPending ? "Starting…" : "Start case"}
          </Button>
        </>
      }
    >
      <form id="schema-start" onSubmit={onSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {properties.map(([k, p]) => {
          const label = humanize(k);
          const set = (v: Value) => setValues({ ...values, [k]: v });
          if (p.type === "boolean") {
            return (
              <label key={k} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={values[k] === true} onChange={(e) => set(e.target.checked)} />
                {label}
              </label>
            );
          }
          return (
            <Field key={k} label={label} hint={p.description}>
              {(fieldProps) =>
                p.enum ? (
                  <select {...fieldProps} className={inputClass} required={required.has(k)} value={String(values[k])} onChange={(e) => set(e.target.value)}>
                    <option value="">Select…</option>
                    {p.enum.map((option) => (
                      <option key={String(option)} value={String(option)}>
                        {humanize(String(option))}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    {...fieldProps}
                    className={inputClass}
                    type={p.type === "integer" || p.type === "number" ? "number" : p.format === "date" ? "date" : "text"}
                    required={required.has(k)}
                    pattern={p.pattern}
                    minLength={p.minLength}
                    maxLength={p.maxLength}
                    min={p.minimum}
                    max={p.maximum}
                    step={p.type === "number" ? "any" : undefined}
                    value={String(values[k])}
                    onChange={(e) => set(e.target.value)}
                  />
                )
              }
            </Field>
          );
        })}
      </form>
      {unsupported.length > 0 && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-amber-800">
          <AlertTriangle aria-hidden className="h-3.5 w-3.5" /> Fields this form cannot edit: {unsupported.join(", ")}
        </p>
      )}
      <ErrorMessage error={start.error} className="mt-4" />
    </Modal>
  );
}
