import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { useAddRuleVersion, useCountryRules, useSanctionsLists } from "@/services/enterprise";
import type { Country, CountryRules } from "@/types/enterprise";

const DOCUMENTS = ["passport", "national_id"] as const;

function RulesForm({ country, current, onDone }: { country: Country; current: CountryRules; onDone: () => void }) {
  const add = useAddRuleVersion(country.id);
  const lists = useSanctionsLists();
  const [rules, setRules] = useState<CountryRules>(structuredClone(current));
  const [effective, setEffective] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("");
  const kyc = (patch: Partial<CountryRules["kyc"]>) => setRules({ ...rules, kyc: { ...rules.kyc, ...patch } });
  const pay = (patch: Partial<CountryRules["payments"]>) => setRules({ ...rules, payments: { ...rules.payments, ...patch } });
  const toggle = <T,>(items: T[], item: T, on: boolean) => (on ? [...items, item] : items.filter((i) => i !== item));
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate({ rules, effective_from: effective, note }, { onSuccess: onDone });
  };
  const input = "rounded-md border border-slate-200 px-2 py-1 text-xs";
  return (
    <form aria-label="New rules version" onSubmit={onSubmit} className="space-y-2 rounded-lg border border-slate-200 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1">
          Minimum age
          <input aria-label="Minimum age" type="number" min={14} max={25} className={`${input} w-16`} value={rules.kyc.min_age} onChange={(e) => kyc({ min_age: Number(e.target.value) })} />
        </label>
        {DOCUMENTS.map((d) => (
          <label key={d} className="flex items-center gap-1">
            <input type="checkbox" checked={rules.kyc.identity_documents.includes(d)} onChange={(e) => kyc({ identity_documents: toggle(rules.kyc.identity_documents, d, e.target.checked) })} />
            {d === "passport" ? "Passport" : "National ID"}
          </label>
        ))}
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={rules.kyc.proof_of_address} onChange={(e) => kyc({ proof_of_address: e.target.checked })} />
          Proof of address
        </label>
      </div>
      <fieldset className="flex flex-wrap gap-3">
        <legend className="sr-only">Sanctions lists</legend>
        {lists.data?.map((l) => (
          <label key={l.list_id} className="flex items-center gap-1" title={l.description}>
            <input
              type="checkbox"
              checked={rules.screening.lists.includes(l.list_id)}
              onChange={(e) => setRules({ ...rules, screening: { lists: toggle(rules.screening.lists, l.list_id, e.target.checked) } })}
            />
            {l.list_id}
          </label>
        ))}
      </fieldset>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1">
          Cut-off
          <input aria-label="Cut-off" type="time" className={input} value={rules.payments.cutoff} onChange={(e) => pay({ cutoff: e.target.value })} />
        </label>
        <label className="flex items-center gap-1">
          High value from
          <input aria-label="High-value threshold" type="number" min={1} className={`${input} w-32`} value={rules.payments.high_value_major} onChange={(e) => pay({ high_value_major: Number(e.target.value) })} />
          {country.default_currency}
        </label>
        <label className="flex items-center gap-1">
          Payment limit
          <input aria-label="Payment limit" type="number" min={1} className={`${input} w-36`} value={rules.payments.max_payment_major} onChange={(e) => pay({ max_payment_major: Number(e.target.value) })} />
          {country.default_currency}
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1">
          Effective from
          <input aria-label="Effective from" type="date" className={input} value={effective} onChange={(e) => setEffective(e.target.value)} required />
        </label>
        <input aria-label="Reason" placeholder="Reason for the change" className={`${input} min-w-64 flex-1`} value={note} onChange={(e) => setNote(e.target.value)} required />
        <Button size="sm" type="submit" disabled={add.isPending}>
          Save as a new version
        </Button>
        <Button size="sm" variant="secondary" onClick={onDone}>
          Cancel
        </Button>
      </div>
      <ErrorMessage error={add.error} />
    </form>
  );
}

/** The country's rules in force today, their versions, and (for managers) a new version. */
export function CountryRulesSection({ country }: { country: Country }) {
  const { can } = useAuth();
  const rules = useCountryRules(country.id);
  const [editing, setEditing] = useState(false);
  const r = rules.data?.effective;
  return (
    <section aria-label="Country rules" className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Rules in force</h3>
        {rules.data?.current && <span className="text-xs text-slate-500">version {rules.data.current.version} since {rules.data.current.effective_from}</span>}
        {can("countries:manage") && r && !editing && (
          <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
            New version
          </Button>
        )}
      </div>
      <ErrorMessage error={rules.error} />
      {r && (
        <dl className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-3">
          <div>
            <dt className="text-slate-500">Account opening</dt>
            <dd>
              Age {r.kyc.min_age}+ · {r.kyc.identity_documents.map((d) => (d === "passport" ? "passport" : "national ID")).join(" or ")}
              {r.kyc.proof_of_address ? " · proof of address" : " · no proof of address"}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">Sanctions screening</dt>
            <dd>{r.screening.lists.join(", ")}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Payments</dt>
            <dd>
              Cut-off {r.payments.cutoff} local · high value from {r.payments.high_value_major.toLocaleString()} · limit{" "}
              {r.payments.max_payment_major.toLocaleString()} {country.default_currency}
            </dd>
          </div>
        </dl>
      )}
      {editing && r && <RulesForm country={country} current={r} onDone={() => setEditing(false)} />}
      {rules.data && rules.data.versions.length > 0 && (
        <ul aria-label="Rule versions" className="text-xs text-slate-500">
          {rules.data.versions.map((v) => (
            <li key={v.id}>
              v{v.version} from {v.effective_from}: {v.note}
              {v.created_by_username && ` (${v.created_by_username})`}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
