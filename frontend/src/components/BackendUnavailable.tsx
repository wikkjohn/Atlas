import { RefreshCw, ServerCrash } from "lucide-react";

interface BackendUnavailableProps {
  onRetry: () => void;
  retrying: boolean;
  detail?: string;
}

export function BackendUnavailable({ onRetry, retrying, detail }: BackendUnavailableProps) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-rose-900 shadow-sm"
    >
      <div className="flex items-start gap-4">
        <ServerCrash aria-hidden className="mt-0.5 h-6 w-6 shrink-0 text-rose-600" />
        <div className="flex-1">
          <h2 className="text-base font-semibold">The ATLAS API is unavailable</h2>
          <p className="mt-1 text-sm text-rose-800">
            The interface could not reach the backend service, so no platform data can be
            shown. Make sure the backend is running (for example{" "}
            <code className="rounded bg-rose-100 px-1 font-mono text-xs">make backend</code>) and
            try again.
          </p>
          {detail && <p className="mt-2 font-mono text-xs text-rose-700">{detail}</p>}
          <button
            type="button"
            onClick={onRetry}
            disabled={retrying}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-rose-700 disabled:opacity-60"
          >
            <RefreshCw aria-hidden className={`h-4 w-4 ${retrying ? "animate-spin" : ""}`} />
            {retrying ? "Retrying…" : "Retry connection"}
          </button>
        </div>
      </div>
    </div>
  );
}
