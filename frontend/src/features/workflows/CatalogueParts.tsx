import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useCountries, useUsers } from "@/services/enterprise";
import { humanize } from "@/services/format";
import { type CatalogueFilters, type VersionAction, useClassify, useSetDefinitionStatus, useStoredVersions } from "@/services/workflows";
import type { CatalogueFacetName, CatalogueResult, DefinitionStatus, StoredDefinition, WorkflowSummary } from "@/types/workflows";

export const STATUS_TONE: Record<DefinitionStatus, Tone> = {
  draft: "neutral",
  in_review: "warn",
  active: "good",
  retired: "neutral",
};

const FILTERS: [CatalogueFacetName, string][] = [
  ["department", "Department"],
  ["country", "Country"],
  ["product", "Product"],
  ["status", "Status"],
];

/** One select per facet, each option with how many workflows it would leave. */
export function CatalogueFilterBar({
  filters,
  facets,
  onChange,
}: {
  filters: CatalogueFilters;
  facets: CatalogueResult["facets"] | undefined;
  onChange: (filters: CatalogueFilters) => void;
}) {
  const active = FILTERS.some(([name]) => filters[name]);
  return (
    <div className="grid grid-cols-2 gap-2">
      {FILTERS.map(([name, label]) => {
        const chosen = filters[name] ?? "";
        const values = facets?.[name] ?? [];
        return (
          <select
            key={name}
            aria-label={`Filter by ${label.toLowerCase()}`}
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs"
            value={chosen}
            onChange={(e) => onChange({ ...filters, [name]: e.target.value || undefined })}
          >
            <option value="">{label}: any</option>
            {chosen && !values.some((f) => f.value === chosen) && <option value={chosen}>{name === "status" ? humanize(chosen) : chosen} (0)</option>}
            {values.map((f) => (
              <option key={f.value} value={f.value}>
                {name === "status" || name === "product" ? humanize(f.value) : f.value} ({f.count})
              </option>
            ))}
          </select>
        );
      })}
      {active && (
        <button
          type="button"
          className="col-span-2 text-left text-xs text-sky-700 hover:underline"
          onClick={() => onChange({ q: filters.q })}
        >
          Clear filters
        </button>
      )}
    </div>
  );
}

/** Department, countries, products and owner of a workflow, with an edit button. */
export function Classification({ workflow }: { workflow: WorkflowSummary }) {
  const { can } = useAuth();
  const [editing, setEditing] = useState(false);
  const parts = [
    workflow.department ? `Department: ${workflow.department}` : "No department",
    workflow.countries?.length ? `Countries: ${workflow.countries.join(", ")}` : null,
    workflow.products?.length ? `Products: ${workflow.products.map(humanize).join(", ")}` : null,
    workflow.owner_username ? `Owned by ${workflow.owner_username}` : null,
  ].filter(Boolean);
  return (
    <div aria-label="Classification" className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
      <span>{parts.join(" · ")}</span>
      {workflow.tags?.map((t) => (
        <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
          #{t}
        </span>
      ))}
      {can("workflows:define") && (
        <button type="button" className="text-sky-700 hover:underline" onClick={() => setEditing(true)}>
          Classify
        </button>
      )}
      {editing && <ClassifyDialog workflow={workflow} onClose={() => setEditing(false)} />}
    </div>
  );
}

const words = (text: string) =>
  text
    .split(",")
    .map((w) => w.trim())
    .filter(Boolean);

function ClassifyDialog({ workflow, onClose }: { workflow: WorkflowSummary; onClose: () => void }) {
  const { user, can } = useAuth();
  const classify = useClassify(workflow.workflow_id);
  const countries = useCountries({});
  const users = useUsers({ limit: 100 }, can("users:read"));
  const [department, setDepartment] = useState(workflow.department ?? "");
  const [chosen, setChosen] = useState<string[]>(workflow.countries ?? []);
  const [products, setProducts] = useState((workflow.products ?? []).join(", "));
  const [tags, setTags] = useState((workflow.tags ?? []).join(", "));
  const [owner, setOwner] = useState(workflow.owner_id ?? "");

  const owners = users.data?.items ?? (user ? [user] : []);
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    classify.mutate(
      { department: department.trim() || null, countries: chosen, products: words(products), tags: words(tags), owner_id: owner || null },
      { onSuccess: onClose },
    );
  };
  return (
    <Modal
      title={`Classify ${workflow.workflow_id}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="classify" disabled={classify.isPending}>
            {classify.isPending ? "Saving…" : "Save classification"}
          </Button>
        </>
      }
    >
      <form id="classify" onSubmit={onSubmit} className="space-y-3">
        <Field label="Department">{(p) => <input {...p} className={inputClass} value={department} onChange={(e) => setDepartment(e.target.value)} />}</Field>
        <fieldset className="text-sm">
          <legend className="text-xs font-medium text-slate-700">Countries</legend>
          <div className="mt-1 flex flex-wrap gap-3">
            {countries.data?.items.map((c) => (
              <label key={c.id} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={chosen.includes(c.iso_country_code)}
                  onChange={(e) =>
                    setChosen(e.target.checked ? [...chosen, c.iso_country_code] : chosen.filter((x) => x !== c.iso_country_code))
                  }
                />
                {c.iso_country_code}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="Products" hint="Comma-separated, e.g. current, savings">
          {(p) => <input {...p} className={inputClass} value={products} onChange={(e) => setProducts(e.target.value)} />}
        </Field>
        <Field label="Tags" hint="Comma-separated">
          {(p) => <input {...p} className={inputClass} value={tags} onChange={(e) => setTags(e.target.value)} />}
        </Field>
        <Field label="Owner">
          {(p) => (
            <select {...p} className={inputClass} value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">No owner</option>
              {workflow.owner_id && !owners.some((u) => u.id === workflow.owner_id) && (
                <option value={workflow.owner_id}>{workflow.owner_username ?? "Current owner"}</option>
              )}
              {owners.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username}
                </option>
              ))}
            </select>
          )}
        </Field>
      </form>
      <ErrorMessage error={classify.error} className="mt-3" />
    </Modal>
  );
}

const ACTION_LABEL: Record<VersionAction, string> = {
  submit: "Submit for review",
  approve: "Approve",
  return: "Return to draft",
  retire: "Retire",
  reactivate: "Reactivate",
};

function actionsFor(status: DefinitionStatus): VersionAction[] {
  switch (status) {
    case "draft":
      return ["submit"];
    case "in_review":
      return ["approve", "return"];
    case "active":
      return ["retire"];
    case "retired":
      return ["reactivate"];
  }
}

function VersionRow({ v, selected, onSelect }: { v: StoredDefinition; selected: boolean; onSelect: () => void }) {
  const { can } = useAuth();
  const act = useSetDefinitionStatus();
  const [note, setNote] = useState("");
  const reviewing = v.status === "in_review";
  return (
    <li className={`space-y-1.5 rounded-lg border p-3 text-sm ${selected ? "border-navy-700 bg-navy-900/5" : "border-slate-200"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="font-medium text-slate-900 hover:underline" onClick={onSelect}>
          v{v.version}
        </button>
        <StatusPill compact tone={STATUS_TONE[v.status]} label={humanize(v.status)} />
        <span className="text-xs text-slate-500">
          imported by {v.imported_by_username ?? "system"} {formatTimestamp(v.imported_at)}
          {v.submitted_by_username && ` · submitted by ${v.submitted_by_username}`}
          {v.reviewed_by_username && ` · ${v.status === "draft" ? "returned" : "approved"} by ${v.reviewed_by_username}`}
        </span>
      </div>
      {v.review_note && <p className="text-xs text-slate-600">“{v.review_note}”</p>}
      {can("workflows:define") && (
        <div className="flex flex-wrap items-center gap-1.5">
          {reviewing && (
            <input
              aria-label={`Review note for v${v.version}`}
              placeholder="Review note (required to return)"
              className="min-w-48 flex-1 rounded-md border border-slate-200 px-2 py-1 text-xs"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
          {actionsFor(v.status).map((action) => (
            <Button
              key={action}
              size="sm"
              variant={action === "approve" || action === "submit" ? "primary" : "secondary"}
              disabled={act.isPending || (action === "return" && !note.trim())}
              onClick={() => act.mutate({ workflowId: v.workflow_id, version: v.version, action, note })}
            >
              {ACTION_LABEL[action]} v{v.version}
            </Button>
          ))}
        </div>
      )}
      <ErrorMessage error={act.error} />
    </li>
  );
}

/** Every stored version of a workflow with its review state and the actions it allows:
 * draft → submit → approve (someone else; tests must pass) or return → retire/reactivate. */
export function VersionsPanel({
  workflowId,
  shown,
  onShow,
}: {
  workflowId: string;
  shown: number;
  onShow: (version: number) => void;
}) {
  const versions = useStoredVersions(workflowId);
  return (
    <section aria-label="Versions" className="space-y-2">
      <h3 className="text-sm font-semibold text-slate-900">Versions and review</h3>
      <ErrorMessage error={versions.error} />
      <ul className="space-y-2">
        {versions.data
          ?.slice()
          .reverse()
          .map((v) => <VersionRow key={v.version} v={v} selected={v.version === shown} onSelect={() => onShow(v.version)} />)}
      </ul>
      <p className="text-xs text-slate-500">
        Imported versions start as drafts. Approval needs someone other than the author and a passing generated test run
        of that version.
      </p>
    </section>
  );
}
