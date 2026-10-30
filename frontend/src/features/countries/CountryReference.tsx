import { type FormEvent, useState } from "react";

import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Modal } from "@/components/Modal";
import { useCheckCountryValue, useCountryCalendar, useCountrySamples, useCurrencies } from "@/services/enterprise";
import type { Country } from "@/types/enterprise";

const WEEKDAYS = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function Term({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-sm text-slate-900">{children}</dd>
    </div>
  );
}

function CalendarSection({ country }: { country: Country }) {
  const [year, setYear] = useState(2026);
  const calendar = useCountryCalendar(country.id, year);
  return (
    <section aria-label="Holiday calendar" className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Public holidays</h3>
        <select
          aria-label="Year"
          className="rounded-md border border-slate-200 px-1.5 py-0.5 text-xs"
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
        >
          {[2025, 2026, 2027, 2028].map((y) => (
            <option key={y}>{y}</option>
          ))}
        </select>
        {calendar.data && <span role="status" className="text-xs text-slate-500">{calendar.data.business_days} business days</span>}
      </div>
      <ErrorMessage error={calendar.error} />
      {calendar.data && calendar.data.holidays.length === 0 && <p className="text-xs text-slate-500">No holidays computed from rules.</p>}
      <ul className="grid grid-cols-1 gap-x-4 text-xs sm:grid-cols-2">
        {calendar.data?.holidays.map((h) => (
          <li key={h.date + h.name} className="flex gap-2">
            <span className="font-mono text-slate-500">{h.date}</span>
            <span className="text-slate-800">
              {h.name}
              {h.observed !== h.date && <span className="text-slate-500"> (observed {h.observed})</span>}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CheckSection({ country }: { country: Country }) {
  const check = useCheckCountryValue(country.id);
  const [kind, setKind] = useState("postal_code");
  const [value, setValue] = useState("");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    check.mutate({ kind, value });
  };
  return (
    <section aria-label="Check a value" className="space-y-2">
      <h3 className="text-sm font-semibold text-slate-900">Check a value</h3>
      <form onSubmit={onSubmit} className="flex flex-wrap items-center gap-2">
        <select aria-label="Kind" className="rounded-md border border-slate-200 px-2 py-1 text-xs" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="postal_code">Postal code</option>
          <option value="national_id">National ID</option>
          <option value="passport">Passport</option>
        </select>
        <input
          aria-label="Value"
          className="rounded-md border border-slate-200 px-2 py-1 text-xs"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          required
        />
        <Button size="sm" variant="secondary" type="submit" disabled={check.isPending}>
          Check
        </Button>
        {check.data && (
          <span role="status" className={`text-xs ${check.data.valid ? "text-emerald-700" : "text-rose-700"}`}>
            {check.data.valid
              ? `${check.data.value} matches the format`
              : check.data.masks.length
                ? `${check.data.value} does not match ${check.data.masks.join(" or ")}`
                : "No format is defined for this country"}
          </span>
        )}
      </form>
      <ErrorMessage error={check.error} />
    </section>
  );
}

function SamplesSection({ country }: { country: Country }) {
  const [seed, setSeed] = useState(0);
  const samples = useCountrySamples(country.id, seed);
  return (
    <section aria-label="Synthetic samples" className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Synthetic samples</h3>
        <Button size="sm" variant="secondary" onClick={() => setSeed(seed + 1)}>
          New samples
        </Button>
      </div>
      <ErrorMessage error={samples.error} />
      <ul className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
        {samples.data?.map((s, i) => (
          <li key={i} className="rounded-md border border-slate-200 p-2">
            {s.national_id && <div className="font-mono">ID {s.national_id}</div>}
            <div className="font-mono">Passport {s.passport}</div>
            <div className="mt-1 text-slate-600">
              {s.address_lines.map((line) => (
                <div key={line}>{line}</div>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A country's reference data: identifiers, money, calendar, documents and addresses. */
export function CountryReference({ country, onClose }: { country: Country; onClose: () => void }) {
  const currencies = useCurrencies();
  const currency = currencies.data?.find((c) => c.code === country.default_currency);
  const address = country.address_format;
  return (
    <Modal wide title={`${country.country_name} (${country.iso_country_code})`} onClose={onClose}>
      <div className="space-y-5">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Term label="ISO codes">
            {country.iso_country_code} / {country.iso_alpha3 ?? "—"}
          </Term>
          <Term label="Currency">
            {country.default_currency}
            {currency && ` · ${currency.name}, ${currency.minor_units} decimal${currency.minor_units === 1 ? "" : "s"}`}
          </Term>
          <Term label="Calling code">{country.calling_code ?? "—"}</Term>
          <Term label="Time zone">{country.default_timezone}</Term>
          <Term label="Weekend">{(country.weekend_days ?? []).map((d) => WEEKDAYS[d]).join(" and ") || "—"}</Term>
          <Term label="Languages">{country.supported_languages.join(", ")}</Term>
          <Term label="Banking supervisor">
            {country.regulator ? `${country.regulator.name} (${country.regulator.abbreviation})` : "—"}
          </Term>
          <Term label="Reference data">{country.reference_version ?? "not loaded"}</Term>
        </dl>
        <section aria-label="Identity documents" className="space-y-1">
          <h3 className="text-sm font-semibold text-slate-900">Identity documents</h3>
          <table className="text-xs">
            <tbody>
              {(country.identity_documents ?? []).map((d) => (
                <tr key={d.type}>
                  <td className="pr-4 text-slate-800">{d.name}</td>
                  <td className="pr-4 font-mono text-slate-600">{d.mask}</td>
                  <td className="font-mono text-slate-500">e.g. {d.example}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        {address && (
          <section aria-label="Address format" className="space-y-1">
            <h3 className="text-sm font-semibold text-slate-900">Address format</h3>
            <p className="font-mono text-xs text-slate-600">{address.lines.join(" ⏎ ")}</p>
            <p className="text-xs text-slate-600">
              {address.postal_code_masks.length
                ? `Postal codes: ${address.postal_code_masks.join(", ")} (e.g. ${address.postal_code_example})`
                : "No postal codes in use."}
              {address.requires_region && " A state or province is part of the address."}
            </p>
          </section>
        )}
        <CalendarSection country={country} />
        <CheckSection country={country} />
        <SamplesSection country={country} />
        {(country.reference_notes ?? []).length > 0 && (
          <ul aria-label="Notes" className="list-disc pl-5 text-xs text-slate-500">
            {country.reference_notes!.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        <p className="text-xs text-slate-400">
          Compiled for the simulation: masks approximate real formats (9 a digit, A a letter, X either); regulators and holidays are not authoritative.
        </p>
      </div>
    </Modal>
  );
}
