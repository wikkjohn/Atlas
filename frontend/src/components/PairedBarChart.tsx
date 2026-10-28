import { useState } from "react";

/** Validated categorical slots 1–2 (light surface): baseline blue, candidate orange. */
export const SERIES_COLORS = { baseline: "#2a78d6", candidate: "#eb6834" } as const;

export interface PairedRow {
  label: string;
  baseline: number | null;
  candidate: number | null;
}

interface PairedBarChartProps {
  title: string;
  rows: PairedRow[];
  format: (value: number) => string;
  seriesLabels?: { baseline: string; candidate: string };
  caption?: string;
}

/**
 * Horizontal paired bars on one shared scale (never two axes). Identity is carried by a
 * legend and by row order, values are printed at each bar's tip in text ink, every bar
 * has a hover/focus tooltip, and a table view gives the same numbers without colour.
 */
export function PairedBarChart({
  title,
  rows,
  format,
  seriesLabels = { baseline: "Baseline", candidate: "Candidate" },
  caption,
}: PairedBarChartProps) {
  const [showTable, setShowTable] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const max = Math.max(0, ...rows.flatMap((r) => [r.baseline ?? 0, r.candidate ?? 0]));
  const width = (value: number | null) => (max > 0 && value ? `${(value / max) * 100}%` : "0%");

  return (
    <figure aria-label={title} className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <figcaption className="text-sm font-semibold text-slate-900">{title}</figcaption>
        <div className="flex items-center gap-3 text-xs text-slate-600">
          {(["baseline", "candidate"] as const).map((series) => (
            <span key={series} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIES_COLORS[series] }} />
              {seriesLabels[series]}
            </span>
          ))}
          <button
            type="button"
            className="text-xs text-navy-700 underline-offset-2 hover:underline"
            onClick={() => setShowTable(!showTable)}
          >
            {showTable ? "Show chart" : "Show table"}
          </button>
        </div>
      </div>
      {showTable ? (
        <table aria-label={`${title} (table)`} className="min-w-full text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr>
              <th className="py-1 pr-3 font-medium" />
              <th className="py-1 pr-3 text-right font-medium">{seriesLabels.baseline}</th>
              <th className="py-1 text-right font-medium">{seriesLabels.candidate}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r) => (
              <tr key={r.label}>
                <td className="py-1 pr-3 text-slate-700">{r.label}</td>
                <td className="py-1 pr-3 text-right tabular-nums">{r.baseline == null ? "—" : format(r.baseline)}</td>
                <td className="py-1 text-right tabular-nums">{r.candidate == null ? "—" : format(r.candidate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="space-y-3">
          {rows.map((r) => (
            <div key={r.label} className="grid grid-cols-[minmax(6rem,10rem)_1fr] items-center gap-3">
              <div className="text-xs text-slate-600">{r.label}</div>
              <div className="space-y-[2px] border-l border-slate-200">
                {(["baseline", "candidate"] as const).map((series) => {
                  const value = r[series];
                  const id = `${r.label}:${series}`;
                  const text = value == null ? "—" : format(value);
                  return (
                    <div
                      key={series}
                      className="relative flex items-center gap-1.5 py-0.5 outline-none focus-visible:ring-2 focus-visible:ring-navy-700/30"
                      tabIndex={0}
                      aria-label={`${r.label}, ${seriesLabels[series]}: ${text}`}
                      onMouseEnter={() => setHover(id)}
                      onMouseLeave={() => setHover(null)}
                      onFocus={() => setHover(id)}
                      onBlur={() => setHover(null)}
                    >
                      <div
                        className="h-2.5 rounded-r"
                        style={{ width: width(value), background: SERIES_COLORS[series], minWidth: value ? 2 : 0 }}
                      />
                      <span className="text-[11px] whitespace-nowrap text-slate-700 tabular-nums">{text}</span>
                      {hover === id && (
                        <div
                          role="tooltip"
                          className="absolute bottom-full left-0 z-10 mb-1 rounded-md bg-slate-900 px-2 py-1 text-[11px] whitespace-nowrap text-white shadow"
                        >
                          {r.label} · {seriesLabels[series]}: {text}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
      {caption && <p className="text-[11px] text-slate-500">{caption}</p>}
    </figure>
  );
}
