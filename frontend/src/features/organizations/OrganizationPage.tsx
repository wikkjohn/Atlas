import { Building2, ChevronDown, ChevronRight, Plus } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { CHILD_TYPE, ORG_TYPE_LABELS, REGION_LABELS } from "@/services/format";
import {
  useAncestors,
  useCountries,
  useCreateOrganization,
  useEmployees,
  useOrganization,
  useOrganizations,
  useUpdateOrganization,
} from "@/services/enterprise";
import type { Organization, OrganizationType, Region } from "@/types/enterprise";

function TypeBadge({ type }: { type: OrganizationType }) {
  return (
    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-slate-600 uppercase">
      {ORG_TYPE_LABELS[type]}
    </span>
  );
}

interface TreeNodeProps {
  organization: Organization;
  depth: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  initiallyOpen?: boolean;
}

function TreeNode({ organization, depth, selectedId, onSelect, initiallyOpen = false }: TreeNodeProps) {
  const [open, setOpen] = useState(initiallyOpen);
  const hasChildren = organization.child_count > 0;
  const children = useOrganizations({ parent_id: organization.id }, open && hasChildren);
  const selected = organization.id === selectedId;

  return (
    <li>
      <div
        className={`flex items-center gap-1 rounded-md py-1 pr-2 ${selected ? "bg-navy-900/5 ring-1 ring-navy-700/20" : "hover:bg-slate-50"}`}
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
      >
        <button
          type="button"
          aria-label={open ? `Collapse ${organization.name}` : `Expand ${organization.name}`}
          aria-expanded={hasChildren ? open : undefined}
          disabled={!hasChildren}
          onClick={() => setOpen(!open)}
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-400 hover:text-slate-700 disabled:invisible"
        >
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
        <button
          type="button"
          onClick={() => onSelect(organization.id)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm"
        >
          <span
            className={`truncate ${selected ? "font-semibold text-navy-900" : "text-slate-800"} ${organization.status === "inactive" ? "text-slate-400 line-through" : ""}`}
          >
            {organization.name}
          </span>
          {organization.country_code && (
            <span className="font-mono text-[10px] text-slate-400">{organization.country_code}</span>
          )}
        </button>
      </div>
      {open && hasChildren && (
        <ul>
          {children.isLoading && (
            <li className="py-1 text-xs text-slate-400" style={{ paddingLeft: `${depth * 16 + 32}px` }}>
              Loading…
            </li>
          )}
          {children.data?.items.map((child) => (
            <TreeNode
              key={child.id}
              organization={child}
              depth={depth + 1}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function AddUnitDialog({ parent, onClose }: { parent: Organization | null; onClose: () => void }) {
  const childType: OrganizationType = parent ? (CHILD_TYPE[parent.organization_type] ?? "team") : "global_bank";
  const create = useCreateOrganization();
  const [name, setName] = useState("");
  const [region, setRegion] = useState<Region>("europe");
  const needsCountry = childType === "country_subsidiary";
  const countries = useCountries(
    needsCountry ? { region: parent?.region ?? undefined, operational_status: "active" } : {},
  );
  const [countryId, setCountryId] = useState("");

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      {
        name,
        organization_type: childType,
        parent_organization_id: parent?.id ?? null,
        region: childType === "regional_headquarters" ? region : undefined,
        country_id: needsCountry ? countryId || null : undefined,
      },
      { onSuccess: onClose },
    );
  };

  return (
    <Modal
      title={`Add ${ORG_TYPE_LABELS[childType].toLowerCase()}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="add-unit" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create"}
          </Button>
        </>
      }
    >
      <form id="add-unit" onSubmit={onSubmit} className="space-y-4">
        {parent && (
          <p className="text-sm text-slate-600">
            Inside <span className="font-medium text-slate-900">{parent.name}</span>
            {parent.country_name && ` · ${parent.country_name}`}
          </p>
        )}
        <Field label="Name">
          {(p) => (
            <input
              {...p}
              className={inputClass}
              required
              minLength={2}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          )}
        </Field>
        {childType === "regional_headquarters" && (
          <Field label="Region">
            {(p) => (
              <select
                {...p}
                className={inputClass}
                value={region}
                onChange={(e) => setRegion(e.target.value as Region)}
              >
                {Object.entries(REGION_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}
        {needsCountry && (
          <Field
            label="Country"
            hint="Only active countries in this region can host a subsidiary."
          >
            {(p) => (
              <select
                {...p}
                className={inputClass}
                required
                value={countryId}
                onChange={(e) => setCountryId(e.target.value)}
              >
                <option value="">Select a country…</option>
                {countries.data?.items.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.country_name} ({c.default_currency})
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}
      </form>
      <ErrorMessage error={create.error} className="mt-4" />
    </Modal>
  );
}

function RenameDialog({ organization, onClose }: { organization: Organization; onClose: () => void }) {
  const update = useUpdateOrganization();
  const [name, setName] = useState(organization.name);
  return (
    <Modal
      title="Rename organization"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="rename-unit" disabled={update.isPending}>
            Save
          </Button>
        </>
      }
    >
      <form
        id="rename-unit"
        onSubmit={(e) => {
          e.preventDefault();
          update.mutate({ id: organization.id, body: { name } }, { onSuccess: onClose });
        }}
      >
        <Field label="Name">
          {(p) => (
            <input
              {...p}
              className={inputClass}
              required
              minLength={2}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          )}
        </Field>
      </form>
      <ErrorMessage error={update.error} className="mt-4" />
    </Modal>
  );
}

function OrganizationDetail({ id }: { id: string }) {
  const { can } = useAuth();
  const organization = useOrganization(id);
  const ancestors = useAncestors(id);
  const update = useUpdateOrganization();
  const [dialog, setDialog] = useState<"add" | "rename" | null>(null);
  const org = organization.data;
  const staffed = org?.organization_type === "department" || org?.organization_type === "team";
  const staff = useEmployees({ organization_id: id, limit: 25 }, Boolean(staffed));
  const canManage = can("organizations:manage");

  if (organization.error) return <ErrorMessage error={organization.error} />;
  if (!org) return <p className="text-sm text-slate-500">Loading…</p>;

  const childType = CHILD_TYPE[org.organization_type];
  const facts: [string, string][] = [
    ["Type", ORG_TYPE_LABELS[org.organization_type]],
    ["Region", org.region ? REGION_LABELS[org.region] : "All regions"],
    ["Country", org.country_name ?? "—"],
    ["Currency", org.currency ?? "—"],
    ["Sub-units", String(org.child_count)],
    ["Staff (direct)", String(org.employee_count)],
  ];

  return (
    <div className="space-y-6">
      <div>
        {ancestors.data && ancestors.data.length > 0 && (
          <p className="mb-1 text-xs text-slate-500">
            {ancestors.data.map((a) => a.name).join(" › ")}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-slate-900">{org.name}</h2>
          <TypeBadge type={org.organization_type} />
          <StatusPill tone={org.status === "active" ? "good" : "neutral"} label={org.status} />
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
        {facts.map(([term, value]) => (
          <div key={term}>
            <dt className="text-xs font-medium tracking-wide text-slate-500 uppercase">{term}</dt>
            <dd className="mt-0.5 text-slate-900">{value}</dd>
          </div>
        ))}
      </dl>

      {canManage && (
        <div className="flex flex-wrap gap-2">
          {childType && org.status === "active" && (
            <Button size="sm" onClick={() => setDialog("add")}>
              <Plus aria-hidden className="h-3.5 w-3.5" />
              Add {ORG_TYPE_LABELS[childType].toLowerCase()}
            </Button>
          )}
          <Button size="sm" variant="secondary" onClick={() => setDialog("rename")}>
            Rename
          </Button>
          {org.organization_type !== "global_bank" && (
            <Button
              size="sm"
              variant="secondary"
              disabled={update.isPending}
              onClick={() =>
                update.mutate({
                  id: org.id,
                  body: { status: org.status === "active" ? "inactive" : "active" },
                })
              }
            >
              {org.status === "active" ? "Deactivate" : "Reactivate"}
            </Button>
          )}
        </div>
      )}
      <ErrorMessage error={update.error} />

      {staffed && (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900">Staff</h3>
            <Link
              to={`/employees?organization_id=${org.id}`}
              className="text-xs font-medium text-navy-700 hover:underline"
            >
              Open in Employees
            </Link>
          </div>
          {staff.data && staff.data.items.length === 0 && (
            <p className="text-sm text-slate-500">No staff assigned.</p>
          )}
          <ul className="divide-y divide-slate-100 text-sm">
            {staff.data?.items.map((e) => (
              <li key={e.id} className="flex justify-between gap-4 py-1.5">
                <span className="text-slate-900">{e.full_name}</span>
                <span className="truncate text-slate-500">{e.job_title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {dialog === "add" && <AddUnitDialog parent={org} onClose={() => setDialog(null)} />}
      {dialog === "rename" && <RenameDialog organization={org} onClose={() => setDialog(null)} />}
    </div>
  );
}

export function OrganizationPage() {
  const { can } = useAuth();
  const roots = useOrganizations({ root_only: true });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creatingRoot, setCreatingRoot] = useState(false);
  const root = roots.data?.items[0];

  useEffect(() => {
    if (!selectedId && root) setSelectedId(root.id);
  }, [root, selectedId]);

  return (
    <>
      <PageHeader
        title="Organization"
        description="Global bank → regional headquarters → country subsidiary → business division → department → team."
      />
      <ErrorMessage error={roots.error} />
      {roots.data && roots.data.total === 0 && (
        <Panel title="No organization yet">
          <div className="flex flex-col items-start gap-3 text-sm text-slate-600">
            <p>
              The hierarchy is empty. Run <code className="font-mono">make seed</code> to create the
              demo bank, or start one here.
            </p>
            {can("organizations:manage") && (
              <Button onClick={() => setCreatingRoot(true)}>
                <Building2 aria-hidden className="h-4 w-4" />
                Create the global bank
              </Button>
            )}
          </div>
        </Panel>
      )}
      {root && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(280px,380px)_1fr]">
          <Panel title="Hierarchy" subtitle="Expand a unit to load its children">
            <ul aria-label="Organization hierarchy" className="-mx-2 -my-2">
              <TreeNode
                organization={root}
                depth={0}
                selectedId={selectedId}
                onSelect={setSelectedId}
                initiallyOpen
              />
            </ul>
          </Panel>
          <Panel title="Details">
            {selectedId ? (
              <OrganizationDetail key={selectedId} id={selectedId} />
            ) : (
              <p className="text-sm text-slate-500">Select a unit.</p>
            )}
          </Panel>
        </div>
      )}
      {creatingRoot && <AddUnitDialog parent={null} onClose={() => setCreatingRoot(false)} />}
    </>
  );
}
