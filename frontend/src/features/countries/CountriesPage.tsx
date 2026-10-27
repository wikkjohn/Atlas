import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { REGION_LABELS } from "@/services/format";
import { useCountries, useCreateCountry, useUpdateCountry } from "@/services/enterprise";
import type { Country, CountryStatus, Region } from "@/types/enterprise";

const STATUS_TONE: Record<CountryStatus, Tone> = {
  active: "good",
  planned: "neutral",
  suspended: "warn",
};

function AddCountryDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateCountry();
  const [form, setForm] = useState({
    iso_country_code: "",
    country_name: "",
    region: "europe" as Region,
    default_currency: "",
    default_timezone: "",
    supported_languages: "",
    operational_status: "planned" as CountryStatus,
  });
  const set = (key: keyof typeof form) => (value: string) => setForm({ ...form, [key]: value });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      {
        ...form,
        supported_languages: form.supported_languages
          .split(",")
          .map((l) => l.trim())
          .filter(Boolean),
      },
      { onSuccess: onClose },
    );
  };

  return (
    <Modal
      title="Add country"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="add-country" disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Add country"}
          </Button>
        </>
      }
    >
      <form id="add-country" onSubmit={onSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="ISO code" hint="ISO 3166-1 alpha-2, e.g. FR">
          {(p) => (
            <input
              {...p}
              className={inputClass}
              maxLength={2}
              required
              value={form.iso_country_code}
              onChange={(e) => set("iso_country_code")(e.target.value.toUpperCase())}
            />
          )}
        </Field>
        <Field label="Country name">
          {(p) => (
            <input
              {...p}
              className={inputClass}
              required
              value={form.country_name}
              onChange={(e) => set("country_name")(e.target.value)}
            />
          )}
        </Field>
        <Field label="Region">
          {(p) => (
            <select
              {...p}
              className={inputClass}
              value={form.region}
              onChange={(e) => set("region")(e.target.value)}
            >
              {Object.entries(REGION_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Currency" hint="ISO 4217, e.g. EUR">
          {(p) => (
            <input
              {...p}
              className={inputClass}
              maxLength={3}
              required
              value={form.default_currency}
              onChange={(e) => set("default_currency")(e.target.value.toUpperCase())}
            />
          )}
        </Field>
        <Field label="Time zone" hint="IANA name, e.g. Europe/Paris">
          {(p) => (
            <input
              {...p}
              className={inputClass}
              required
              value={form.default_timezone}
              onChange={(e) => set("default_timezone")(e.target.value)}
            />
          )}
        </Field>
        <Field label="Languages" hint="Comma-separated, e.g. fr-FR, en">
          {(p) => (
            <input
              {...p}
              className={inputClass}
              required
              value={form.supported_languages}
              onChange={(e) => set("supported_languages")(e.target.value)}
            />
          )}
        </Field>
        <Field label="Operational status">
          {(p) => (
            <select
              {...p}
              className={inputClass}
              value={form.operational_status}
              onChange={(e) => set("operational_status")(e.target.value)}
            >
              <option value="planned">Planned</option>
              <option value="active">Active</option>
              <option value="suspended">Suspended</option>
            </select>
          )}
        </Field>
      </form>
      <ErrorMessage error={create.error} className="mt-4" />
    </Modal>
  );
}

function StatusControl({ country }: { country: Country }) {
  const update = useUpdateCountry();
  return (
    <div className="flex items-center gap-2">
      <select
        aria-label={`Status of ${country.country_name}`}
        className="rounded-md border border-slate-200 bg-white py-0.5 pr-6 pl-2 text-xs"
        value={country.operational_status}
        disabled={update.isPending}
        onChange={(e) =>
          update.mutate({ id: country.id, body: { operational_status: e.target.value } })
        }
      >
        <option value="active">Active</option>
        <option value="planned">Planned</option>
        <option value="suspended">Suspended</option>
      </select>
      {update.error && <span className="text-xs text-rose-600">{update.error.message}</span>}
    </div>
  );
}

export function CountriesPage() {
  const { can } = useAuth();
  const [region, setRegion] = useState("");
  const [adding, setAdding] = useState(false);
  const countries = useCountries({ region: region || undefined });
  const canManage = can("countries:manage");

  return (
    <>
      <PageHeader
        title="Countries"
        description="Country configuration registry. A country's status, currency and time zone govern the organizations and staff placed in it."
        actions={
          canManage && (
            <Button onClick={() => setAdding(true)}>
              <Plus aria-hidden className="h-4 w-4" />
              Add country
            </Button>
          )
        }
      />
      <div className="mb-4 flex items-center gap-3">
        <label htmlFor="region-filter" className="text-xs font-medium text-slate-600">
          Region
        </label>
        <select
          id="region-filter"
          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm"
          value={region}
          onChange={(e) => setRegion(e.target.value)}
        >
          <option value="">All regions</option>
          {Object.entries(REGION_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        {countries.data && (
          <span className="text-xs text-slate-500">
            {countries.data.total} configured · target 120
          </span>
        )}
      </div>
      <ErrorMessage error={countries.error} />
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2.5">Country</th>
              <th className="px-4 py-2.5">Region</th>
              <th className="px-4 py-2.5">Currency</th>
              <th className="px-4 py-2.5">Time zone</th>
              <th className="px-4 py-2.5">Languages</th>
              <th className="px-4 py-2.5">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {countries.isLoading && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            )}
            {countries.data?.items.map((country) => (
              <tr key={country.id}>
                <td className="px-4 py-2.5 whitespace-nowrap">
                  <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700">
                    {country.iso_country_code}
                  </span>
                  <span className="font-medium text-slate-900">{country.country_name}</span>
                </td>
                <td className="px-4 py-2.5 text-slate-600">{REGION_LABELS[country.region]}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-slate-700">
                  {country.default_currency}
                </td>
                <td className="px-4 py-2.5 text-slate-600">{country.default_timezone}</td>
                <td className="px-4 py-2.5 text-slate-600">
                  {country.supported_languages.join(", ")}
                </td>
                <td className="px-4 py-2.5">
                  {canManage ? (
                    <StatusControl country={country} />
                  ) : (
                    <StatusPill
                      tone={STATUS_TONE[country.operational_status]}
                      label={country.operational_status}
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {adding && <AddCountryDialog onClose={() => setAdding(false)} />}
    </>
  );
}
