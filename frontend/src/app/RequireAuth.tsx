import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { BackendUnavailable } from "@/components/BackendUnavailable";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, retry } = useAuth();
  const location = useLocation();
  if (status === "checking") {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-500">
        Restoring your session…
      </div>
    );
  }
  if (status === "unreachable") {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16">
        <BackendUnavailable onRetry={retry} retrying={false} />
      </div>
    );
  }
  if (status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <>{children}</>;
}
