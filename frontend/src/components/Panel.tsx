import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Panel({ title, subtitle, actions, children, className = "" }: PanelProps) {
  return (
    <section
      aria-label={title}
      className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}
    >
      <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-3.5">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
        {actions}
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}
