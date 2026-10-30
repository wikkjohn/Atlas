import { Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { WorkflowGraph } from "@/features/workflows/WorkflowGraph";
import { exportDefinition, previewDefinition, useImportDefinition, useLibraryHandlers } from "@/services/workflows";
import type { DraftPreview } from "@/types/workflows";

type Step = Record<string, unknown> & { id: string; type: string; name: string };
type Draft = Record<string, unknown> & { steps: Step[]; version: number };

const PREVIEW_DELAY_MS = 500;
const STEP_TYPES = ["service_task", "ai_task", "approval", "human_task", "decision", "wait", "completion", "failure"];

/** Problems located at a step ("steps.<id>…") grouped by step id. */
function problemsByStep(preview: DraftPreview | null): Record<string, string[]> {
  const found: Record<string, string[]> = {};
  for (const e of preview?.report.errors ?? []) {
    const match = /^steps\.([a-z][a-z0-9_]*)/.exec(e.location);
    if (match) (found[match[1]] ??= []).push(e.message);
  }
  return found;
}

/** Edit a stored workflow as its next version: a step form and the JSON, with the draft
 * validated and drawn as you type. Saving imports it through the usual validation, as a
 * draft that then goes through review. */
export function DefinitionEditor({
  workflowId,
  onClose,
  onSaved,
}: {
  workflowId: string;
  onClose: () => void;
  onSaved: (workflowId: string) => void;
}) {
  const [text, setText] = useState("");
  const [loadError, setLoadError] = useState<unknown>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [preview, setPreview] = useState<DraftPreview | null>(null);
  const [previewError, setPreviewError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const handlers = useLibraryHandlers();
  const save = useImportDefinition();
  const latest = useRef(0);

  useEffect(() => {
    exportDefinition(workflowId).then(
      (document) => setText(JSON.stringify({ ...document, version: Number(document.version) + 1 }, null, 2)),
      setLoadError,
    );
  }, [workflowId]);

  const draft = useMemo<Draft | null>(() => {
    try {
      const parsed = JSON.parse(text) as Draft;
      return Array.isArray(parsed.steps) ? parsed : null;
    } catch {
      return null;
    }
  }, [text]);

  // Validate and lay out the draft shortly after the last change.
  useEffect(() => {
    if (!text) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
      setParseError(null);
    } catch (cause) {
      setParseError(`Not valid JSON: ${(cause as Error).message}`);
      return;
    }
    const call = ++latest.current;
    const timer = setTimeout(() => {
      previewDefinition(parsed).then(
        (result) => {
          if (call === latest.current) {
            setPreview(result);
            setPreviewError(null);
          }
        },
        (error) => call === latest.current && setPreviewError(error),
      );
    }, PREVIEW_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text]);

  const update = (change: (d: Draft) => void) => {
    if (!draft) return;
    const next = structuredClone(draft);
    change(next);
    setText(JSON.stringify(next, null, 2));
  };
  const step = draft?.steps.find((s) => s.id === selected) ?? null;
  const stepIds = draft?.steps.map((s) => s.id) ?? [];
  const errors = problemsByStep(preview);
  const general = (preview?.report.errors ?? []).filter((e) => !e.location.startsWith("steps."));

  const setField = (name: string, value: unknown) =>
    update((d) => {
      const target = d.steps.find((s) => s.id === selected);
      if (!target) return;
      if (value === "" || value === undefined) delete target[name];
      else target[name] = value;
    });

  const addStep = () =>
    update((d) => {
      let n = d.steps.length + 1;
      while (d.steps.some((s) => s.id === `new_step_${n}`)) n += 1;
      const id = `new_step_${n}`;
      d.steps.push({ id, type: "service_task", name: "New step", handler: "core.set_values", params: { values: { note: "set me" } } });
      setSelected(id);
    });

  const removeStep = () =>
    update((d) => {
      d.steps = d.steps.filter((s) => s.id !== selected);
      setSelected(null);
    });

  const onSave = () => {
    if (!draft) return;
    save.mutate(draft, { onSuccess: (result) => onSaved(result.definition.workflow_id) });
  };

  return (
    <Modal
      wide
      title={`Edit ${workflowId}${draft ? ` as v${draft.version}` : ""}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!draft || !preview?.report.valid || save.isPending} onClick={onSave}>
            {save.isPending ? "Saving…" : draft ? `Save as v${draft.version}` : "Save"}
          </Button>
        </>
      }
    >
      <ErrorMessage error={loadError} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(320px,2fr)_3fr]">
        <div className="space-y-3">
          {step ? (
            <fieldset aria-label={`Step ${step.id}`} className="space-y-2 rounded-lg border border-slate-200 p-3">
              <legend className="px-1 font-mono text-xs text-slate-500">{step.id}</legend>
              <Field label="Name">
                {(p) => <input {...p} className={inputClass} value={String(step.name ?? "")} onChange={(e) => setField("name", e.target.value)} />}
              </Field>
              <Field label="Type">
                {(p) => (
                  <select {...p} className={inputClass} value={step.type} onChange={(e) => setField("type", e.target.value)}>
                    {STEP_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              {(step.type === "service_task" || step.type === "ai_task") && (
                <Field label="Handler">
                  {(p) => (
                    <select {...p} className={inputClass} value={String(step.handler ?? "")} onChange={(e) => setField("handler", e.target.value)}>
                      <option value="">Select…</option>
                      {handlers.data
                        ?.filter((h) => h.step_type === step.type)
                        .map((h) => (
                          <option key={h.name} value={h.name}>
                            {h.name}
                          </option>
                        ))}
                    </select>
                  )}
                </Field>
              )}
              <Field label="Next step">
                {(p) => (
                  <select {...p} className={inputClass} value={String(step.next ?? "")} onChange={(e) => setField("next", e.target.value)}>
                    <option value="">(none)</option>
                    {stepIds
                      .filter((id) => id !== step.id)
                      .map((id) => (
                        <option key={id} value={id}>
                          {id}
                        </option>
                      ))}
                  </select>
                )}
              </Field>
              {step.params !== undefined && (
                <Field label="Params (JSON)">
                  {(p) => (
                    <textarea
                      {...p}
                      key={step.id}
                      className={`${inputClass} h-24 font-mono text-xs`}
                      defaultValue={JSON.stringify(step.params, null, 2)}
                      onBlur={(e) => {
                        try {
                          setField("params", JSON.parse(e.target.value));
                        } catch {
                          setParseError("Params are not valid JSON.");
                        }
                      }}
                    />
                  )}
                </Field>
              )}
              {errors[step.id] && (
                <ul aria-label="Step problems" className="list-disc pl-5 text-xs text-rose-700">
                  {errors[step.id].map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              )}
              <Button size="sm" variant="secondary" onClick={removeStep}>
                <Trash2 aria-hidden className="h-3.5 w-3.5" /> Remove step
              </Button>
            </fieldset>
          ) : (
            <p className="text-sm text-slate-500">Select a step in the diagram to edit it, or edit the JSON below.</p>
          )}
          <Button size="sm" variant="secondary" disabled={!draft} onClick={addStep}>
            <Plus aria-hidden className="h-3.5 w-3.5" /> Add a step
          </Button>
          <Field label="Definition (JSON)">
            {(p) => (
              <textarea
                {...p}
                className={`${inputClass} h-72 font-mono text-xs`}
                spellCheck={false}
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
            )}
          </Field>
          {parseError && (
            <p role="alert" className="text-sm text-rose-700">
              {parseError}
            </p>
          )}
        </div>
        <div className="space-y-3">
          <p role="status" className={`text-sm ${preview?.report.valid ? "text-emerald-800" : "text-rose-800"}`}>
            {preview
              ? preview.report.valid
                ? `Valid: v${preview.report.version} can be saved as a draft for review.`
                : `${preview.report.errors.length} problem(s) to fix before saving.`
              : "Checking…"}
          </p>
          {general.length > 0 && (
            <ul aria-label="Definition problems" className="list-disc pl-5 text-xs text-rose-700">
              {general.map((e) => (
                <li key={e.location + e.code}>
                  <span className="font-mono">{e.location}</span>: {e.message}
                </li>
              ))}
            </ul>
          )}
          <ErrorMessage error={previewError ?? save.error} />
          {preview?.graph && <WorkflowGraph graph={preview.graph} errors={errors} selected={selected} onSelect={setSelected} />}
        </div>
      </div>
    </Modal>
  );
}
