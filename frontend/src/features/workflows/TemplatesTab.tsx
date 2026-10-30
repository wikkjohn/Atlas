import { Wand2 } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { formatTimestamp } from "@/features/dashboard/format";
import { useGenerateVariants, useTemplates, useTemplateVariants } from "@/services/workflows";
import type { GenerationResult, GenerationSpec, WorkflowTemplate } from "@/types/workflows";

function describe(property: Record<string, unknown>): string {
  if (Array.isArray(property.enum)) return (property.enum as unknown[]).join(" | ");
  const range =
    property.minimum !== undefined || property.maximum !== undefined
      ? ` ${property.minimum ?? ""}–${property.maximum ?? ""}`
      : "";
  return `${String(property.type ?? "any")}${range}`;
}

function GenerationTable({ result }: { result: GenerationResult }) {
  return (
    <div className="space-y-2">
      <p role="status" className="text-sm text-slate-700">
        {result.dry_run ? "Preview (nothing stored): " : result.stored ? "Stored: " : "Nothing stored: "}
        {result.created} new, {result.updated} updated, {result.unchanged} unchanged, {result.invalid} invalid
      </p>
      <div className="max-h-64 overflow-auto rounded-lg border border-slate-200">
        <table aria-label="Generated variants" className="min-w-full text-xs">
          <thead className="bg-slate-50 text-left text-slate-500">
            <tr>
              <th className="px-3 py-1.5">Workflow</th>
              <th className="px-3 py-1.5">Parameters</th>
              <th className="px-3 py-1.5">Result</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {result.results.map((r) => (
              <tr key={r.variant_key}>
                <td className="px-3 py-1.5 font-mono">
                  {r.workflow_id ?? "—"}
                  {r.version ? ` v${r.version}` : ""}
                </td>
                <td className="px-3 py-1.5 font-mono text-slate-600">{r.variant_key}</td>
                <td className={`px-3 py-1.5 ${r.status === "invalid" ? "text-rose-700" : "text-slate-700"}`}>
                  {r.status}
                  {r.errors.map((e) => (
                    <div key={e.location + e.code}>
                      {e.location}: {e.message}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Preview, then generate: one workflow per parameter set, all stored or none. */
function GenerateDialog({ template, onClose }: { template: WorkflowTemplate; onClose: () => void }) {
  const generate = useGenerateVariants(template.template_id);
  const [text, setText] = useState(() => JSON.stringify({ fixed: template.example }, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerationResult | null>(null);

  const run = (dryRun: boolean) => {
    let spec: GenerationSpec;
    try {
      spec = JSON.parse(text) as GenerationSpec;
      setParseError(null);
    } catch (cause) {
      setParseError(`Not valid JSON: ${(cause as Error).message}`);
      return;
    }
    generate.mutate({ ...spec, dry_run: dryRun }, { onSuccess: setResult });
  };

  return (
    <Modal
      wide
      title={`Generate variants of ${template.template_id}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button variant="secondary" disabled={generate.isPending} onClick={() => run(true)}>
            Preview
          </Button>
          <Button disabled={generate.isPending} onClick={() => run(false)}>
            Generate
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-slate-600">
          Parameter sets are the combinations of <span className="font-mono">grid</span> plus any explicit{" "}
          <span className="font-mono">variants</span>, each over <span className="font-mono">fixed</span>. Each gets a stable
          workflow id from {template.id_range[0]}–{template.id_range[1]}; regenerating publishes new versions only where
          the result changed. If any variant is invalid, nothing is stored.
        </p>
        <Field label="Parameter sets (JSON)">
          {(p) => (
            <textarea
              {...p}
              className={`${inputClass} h-40 font-mono text-xs`}
              spellCheck={false}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setResult(null);
              }}
            />
          )}
        </Field>
        {parseError && (
          <p role="alert" className="text-sm text-rose-700">
            {parseError}
          </p>
        )}
        <ErrorMessage error={generate.error} />
        {result && <GenerationTable result={result} />}
      </div>
    </Modal>
  );
}

export function TemplatesTab({ onOpenWorkflow }: { onOpenWorkflow: (workflowId: string) => void }) {
  const { can } = useAuth();
  const templates = useTemplates();
  const latest = new Map<string, WorkflowTemplate>();
  for (const t of templates.data ?? []) latest.set(t.template_id, t); // sorted by version
  const list = [...latest.values()];
  const [selected, setSelected] = useState<string | null>(null);
  const current = list.find((t) => t.template_id === selected) ?? list[0] ?? null;
  const variants = useTemplateVariants(current?.template_id ?? null);
  const [generating, setGenerating] = useState(false);

  if (templates.error) return <ErrorMessage error={templates.error} />;
  if (templates.data && list.length === 0) return <p className="text-sm text-slate-500">No templates imported yet.</p>;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[300px_1fr]">
      <ul aria-label="Templates" className="space-y-2">
        {list.map((t) => (
          <li key={t.template_id}>
            <button
              type="button"
              onClick={() => setSelected(t.template_id)}
              className={`w-full rounded-lg border p-3 text-left ${current?.template_id === t.template_id ? "border-navy-700 bg-navy-900/5" : "border-slate-200 bg-white hover:bg-slate-50"}`}
            >
              <div className="font-mono text-[11px] text-slate-500">{t.template_id}</div>
              <div className="text-sm font-medium text-slate-900">{t.name}</div>
              <div className="text-xs text-slate-500">
                v{t.version} · {t.variants} workflows · ids {t.id_range[0]}–{t.id_range[1]}
              </div>
            </button>
          </li>
        ))}
      </ul>
      {current && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                {current.name} <span className="text-xs font-normal text-slate-500">v{current.version}</span>
              </h2>
              <p className="mt-1 text-sm text-slate-600">{current.description}</p>
              <p className="mt-1 text-xs text-slate-500">
                Imported {formatTimestamp(current.imported_at)} by {current.imported_by_username ?? "—"}
              </p>
            </div>
            {can("workflows:define") && current.status === "active" && (
              <Button onClick={() => setGenerating(true)}>
                <Wand2 aria-hidden className="h-4 w-4" /> Generate variants
              </Button>
            )}
          </div>
          <table aria-label="Template parameters" className="min-w-full rounded-xl border border-slate-200 bg-white text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500 uppercase">
              <tr>
                <th className="px-4 py-2">Parameter</th>
                <th className="px-4 py-2">Values</th>
                <th className="px-4 py-2">Example</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {Object.entries(current.parameters.properties ?? {}).map(([name, property]) => (
                <tr key={name}>
                  <td className="px-4 py-2 font-mono text-xs">{name}</td>
                  <td className="px-4 py-2 text-xs text-slate-600">{describe(property as Record<string, unknown>)}</td>
                  <td className="px-4 py-2 font-mono text-xs">{JSON.stringify(current.example[name])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-900">Generated workflows ({variants.data?.length ?? 0})</h3>
            <div className="max-h-96 overflow-auto rounded-xl border border-slate-200 bg-white">
              <table aria-label="Template variants" className="min-w-full text-xs">
                <thead className="sticky top-0 bg-slate-50 text-left text-slate-500">
                  <tr>
                    <th className="px-3 py-1.5">Workflow</th>
                    <th className="px-3 py-1.5">Parameters</th>
                    <th className="px-3 py-1.5">From template</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {variants.data?.map((v) => (
                    <tr key={v.workflow_id} className="cursor-pointer hover:bg-slate-50" onClick={() => onOpenWorkflow(v.workflow_id)}>
                      <td className="px-3 py-1.5 font-mono">
                        {v.workflow_id} v{v.definition_version}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-slate-600">{v.variant_key}</td>
                      <td className="px-3 py-1.5 text-slate-600">v{v.template_version}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          {generating && <GenerateDialog template={current} onClose={() => setGenerating(false)} />}
        </div>
      )}
    </div>
  );
}
