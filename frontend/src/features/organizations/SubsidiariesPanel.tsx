import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { REGION_LABELS } from "@/services/format";
import { useGenerateSubsidiaries, useSubsidiaryBlueprint } from "@/services/enterprise";
import { useJob } from "@/services/jobs";
import type { Region } from "@/types/enterprise";

interface GenerateResult {
  countries: number;
  launched: string[];
  failed: Record<string, string>;
  organizations_created: number;
  employees_hired: number;
}

function JobProgress({ id }: { id: string }) {
  const job = useJob(id);
  const client = useQueryClient();
  const status = job.data?.status;
  useEffect(() => {
    if (status === "succeeded" || status === "failed") {
      void client.invalidateQueries({ queryKey: ["organizations"] });
      void client.invalidateQueries({ queryKey: ["countries"] });
    }
  }, [status, client]);
  if (!job.data) return null;
  const result = job.data.result as GenerateResult | null;
  return (
    <div role="status" className="space-y-1 text-xs text-slate-600">
      <p>
        Job #{job.data.job_number}: {job.data.status}
        {job.data.last_error && <span className="text-rose-700"> — {job.data.last_error}</span>}
      </p>
      {result && (
        <p>
          Launched {result.launched.length} of {result.countries} countries: {result.organizations_created} organizations,{" "}
          {result.employees_hired} staff.
        </p>
      )}
      {result &&
        Object.entries(result.failed).map(([code, reason]) => (
          <p key={code} className="text-rose-700">
            {code}: {reason}
          </p>
        ))}
    </div>
  );
}

/** Country subsidiaries generated from the blueprint (Phase 27): coverage and generation. */
export function SubsidiariesPanel() {
  const { can } = useAuth();
  const blueprint = useSubsidiaryBlueprint();
  const generate = useGenerateSubsidiaries();
  const [region, setRegion] = useState("");
  const [codes, setCodes] = useState("");
  const [staff, setStaff] = useState(true);
  const data = blueprint.data;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const countryCodes = codes
      .split(/[\s,]+/)
      .map((c) => c.trim().toUpperCase())
      .filter(Boolean);
    generate.mutate({
      ...(countryCodes.length ? { country_codes: countryCodes } : {}),
      ...(region && !countryCodes.length ? { region } : {}),
      staff,
    });
  };

  return (
    <Panel
      title="Country subsidiaries"
      subtitle={
        data
          ? `Blueprint v${data.version}: ${data.units_per_subsidiary} units and ${data.staff_per_subsidiary} synthetic staff per subsidiary. Launching a country makes it active and builds what its subsidiary is missing.`
          : undefined
      }
    >
      <ErrorMessage error={blueprint.error} />
      <table aria-label="Subsidiary coverage" className="min-w-full text-sm">
        <thead className="text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
          <tr>
            <th className="px-2 py-1">Region</th>
            <th className="px-2 py-1 text-right">Countries</th>
            <th className="px-2 py-1 text-right">Subsidiaries</th>
            <th className="px-2 py-1 text-right">Generated</th>
            <th className="px-2 py-1">Without a subsidiary</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {data?.coverage.map((row) => (
            <tr key={row.region}>
              <td className="px-2 py-1.5 text-slate-900">{REGION_LABELS[row.region]}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{row.countries}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{row.subsidiaries}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{row.generated}</td>
              <td className="px-2 py-1.5 font-mono text-[11px] text-slate-500">
                {row.without_subsidiary.length === 0
                  ? "—"
                  : row.without_subsidiary.slice(0, 12).join(" ") + (row.without_subsidiary.length > 12 ? ` +${row.without_subsidiary.length - 12}` : "")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {can("organizations:manage") && (
        <form onSubmit={onSubmit} aria-label="Generate subsidiaries" className="mt-4 flex flex-wrap items-center gap-2">
          <input
            aria-label="Country codes"
            placeholder="Country codes, e.g. KE GH (blank: all without one)"
            className="w-72 rounded-md border border-slate-200 px-2 py-1 text-xs"
            value={codes}
            onChange={(e) => setCodes(e.target.value)}
          />
          <select
            aria-label="Region"
            className="rounded-md border border-slate-200 px-2 py-1 text-xs"
            value={region}
            disabled={codes.trim() !== ""}
            onChange={(e) => setRegion(e.target.value)}
          >
            <option value="">All regions</option>
            {(Object.keys(REGION_LABELS) as Region[]).map((r) => (
              <option key={r} value={r}>
                {REGION_LABELS[r]}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1 text-xs text-slate-600">
            <input type="checkbox" checked={staff} onChange={(e) => setStaff(e.target.checked)} />
            Hire staff
          </label>
          <Button size="sm" type="submit" disabled={generate.isPending}>
            Generate
          </Button>
        </form>
      )}
      <ErrorMessage error={generate.error} />
      {generate.data && <JobProgress key={generate.data.id} id={generate.data.id} />}
    </Panel>
  );
}
