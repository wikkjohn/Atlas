import { type ReactNode, useId } from "react";

interface FieldProps {
  label: string;
  hint?: string;
  error?: string | null;
  children: (props: { id: string; "aria-invalid": boolean; "aria-describedby"?: string }) => ReactNode;
}

/** Label + control + hint/error, wired up for accessibility. */
export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId();
  const describedBy = error || hint ? `${id}-help` : undefined;
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-slate-700">
        {label}
      </label>
      <div className="mt-1">
        {children({ id, "aria-invalid": Boolean(error), "aria-describedby": describedBy })}
      </div>
      {(error || hint) && (
        <p id={describedBy} className={`mt-1 text-xs ${error ? "text-rose-600" : "text-slate-500"}`}>
          {error ?? hint}
        </p>
      )}
    </div>
  );
}

export const inputClass =
  "block w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-navy-700 focus:ring-2 focus:ring-navy-700/20 focus:outline-none aria-[invalid=true]:border-rose-400 disabled:bg-slate-50";
