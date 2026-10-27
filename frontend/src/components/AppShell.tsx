import { Menu, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { IMPLEMENTED_PHASE, NAV_ITEMS } from "@/app/navigation";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { useHealth, useSystemInfo } from "@/services/queries";

function Brand() {
  return (
    <div className="flex items-center gap-3 px-5 py-5">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gold-500 font-bold text-navy-950">
        A
      </div>
      <div className="leading-tight">
        <div className="text-sm font-bold tracking-[0.18em] text-white">ATLAS</div>
        <div className="text-[10px] font-medium tracking-[0.22em] text-slate-400">GLOBAL BANK</div>
      </div>
    </div>
  );
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Primary" className="flex-1 overflow-y-auto px-3 pb-4">
      <ul className="space-y-0.5">
        {NAV_ITEMS.map(({ label, path, icon: Icon, phase }) => {
          const available = phase <= IMPLEMENTED_PHASE;
          if (!available) {
            return (
              <li key={path}>
                <span
                  aria-disabled="true"
                  title={`Delivered in Phase ${phase}`}
                  className="flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-500"
                >
                  <Icon aria-hidden className="h-4 w-4" />
                  <span className="flex-1 whitespace-nowrap">{label}</span>
                  <span className="rounded bg-navy-800 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
                    Phase {phase}
                  </span>
                </span>
              </li>
            );
          }
          return (
            <li key={path}>
              <NavLink
                to={path}
                end
                onClick={onNavigate}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-navy-700 text-white"
                      : "text-slate-300 hover:bg-navy-800 hover:text-white"
                  }`
                }
              >
                <Icon aria-hidden className="h-4 w-4" />
                {label}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function ConnectionIndicator() {
  const health = useHealth();
  let tone: Tone = "neutral";
  let label = "Checking API…";
  if (health.isError) {
    tone = "bad";
    label = "API unreachable";
  } else if (health.data) {
    const db = health.data.components.database;
    if (db?.status !== "ok") {
      tone = "bad";
      label = "Database unavailable";
    } else if (health.data.status === "degraded") {
      tone = "warn";
      label = "Degraded";
    } else {
      tone = "good";
      label = "All systems operational";
    }
  }
  return (
    <div data-testid="connection-indicator">
      <StatusPill tone={tone} label={label} />
    </div>
  );
}

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const info = useSystemInfo();

  return (
    <div className="flex h-full">
      <aside className="hidden w-68 shrink-0 flex-col bg-navy-900 lg:flex">
        <Brand />
        <Navigation />
        <div className="border-t border-navy-800 px-5 py-3 text-[11px] text-slate-500">
          {info.data ? `v${info.data.version} · ${info.data.environment}` : "ATLAS platform"}
        </div>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 flex lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-navy-950/60"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="relative flex w-68 flex-col bg-navy-900">
            <button
              type="button"
              aria-label="Close navigation"
              className="absolute top-5 right-3 text-slate-400 hover:text-white"
              onClick={() => setMobileOpen(false)}
            >
              <X className="h-5 w-5" />
            </button>
            <Brand />
            <Navigation onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 lg:px-8">
          <button
            type="button"
            aria-label="Open navigation"
            className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden"
            onClick={() => setMobileOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="hidden text-sm font-bold tracking-[0.14em] text-slate-800 min-[440px]:inline lg:hidden">
            ATLAS
          </span>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <div className="rounded-md bg-navy-900 px-1.5 py-1">
              <SyntheticDataBadge />
            </div>
            {info.data && (
              <span className="hidden text-xs text-slate-500 capitalize sm:inline">
                {info.data.environment}
              </span>
            )}
            <ConnectionIndicator />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto px-4 py-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
