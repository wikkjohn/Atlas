import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query, useIdempotencyKey } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type {
  CaseResult,
  HistoryOverview,
  Profile,
  QueuedJob,
  Scenario,
  SimulationRunDetail,
  SimulationRunSummary,
  SimulationStatus,
  StartSimulation,
} from "@/types/simulations";

const POLL_MS = 2000;
const active = (status?: SimulationStatus) => status === "queued" || status === "running";

export const useScenarios = () =>
  useQuery({
    queryKey: ["simulations", "scenarios"],
    queryFn: () => apiGet<Scenario[]>("/api/v1/simulations/scenarios"),
    staleTime: Infinity,
  });

export const useProfiles = () =>
  useQuery({
    queryKey: ["simulations", "profiles"],
    queryFn: () => apiGet<Profile[]>("/api/v1/simulations/profiles"),
    staleTime: Infinity,
  });

export const useSimulationRuns = (offset: number, limit: number) =>
  useQuery({
    queryKey: ["simulations", "runs", offset, limit],
    queryFn: () => apiGet<Page<SimulationRunSummary>>(`/api/v1/simulations${query({ offset, limit })}`),
    placeholderData: keepPreviousData,
    // Keep polling while any listed run is still in progress.
    refetchInterval: (q) => (q.state.data?.items.some((r) => active(r.status)) ? POLL_MS : false),
  });

/** `watch` keeps polling, e.g. while a queued archive or restore job has yet to finish. */
export const useSimulationRun = (id: string | null, watch = false) =>
  useQuery({
    queryKey: ["simulations", "run", id],
    queryFn: () => apiGet<SimulationRunDetail>(`/api/v1/simulations/${id}`),
    enabled: Boolean(id),
    refetchInterval: (q) => (watch || active(q.state.data?.status) ? POLL_MS : false),
  });

export const useHistoryOverview = () =>
  useQuery({
    queryKey: ["simulations", "history"],
    queryFn: () => apiGet<HistoryOverview>("/api/v1/simulations/history"),
  });

/** Queue the archive (or restore) of a run's workflow history as a background job. */
export function useHistoryAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "archive" | "restore" }) =>
      apiPost<QueuedJob>(`/api/v1/simulations/${id}/${action}`, {}),
    onSuccess: invalidate,
  });
}

export const useSimulationCases = (
  id: string | null,
  params: { offset: number; limit: number; mismatched: boolean },
  enabled: boolean,
) =>
  useQuery({
    queryKey: ["simulations", "cases", id, params],
    queryFn: () => apiGet<Page<CaseResult>>(`/api/v1/simulations/${id}/cases${query(params)}`),
    enabled: Boolean(id) && enabled,
    placeholderData: keepPreviousData,
  });

function useInvalidate() {
  const client = useQueryClient();
  return () => void client.invalidateQueries({ queryKey: ["simulations"] });
}

export function useStartSimulation() {
  const invalidate = useInvalidate();
  const once = useIdempotencyKey();
  return useMutation({
    mutationFn: (body: StartSimulation) => apiPost<SimulationRunDetail>("/api/v1/simulations", body, once.key()),
    onSuccess: () => {
      once.renew();
      invalidate();
    },
  });
}

export function useRerunSimulation() {
  const invalidate = useInvalidate();
  const once = useIdempotencyKey();
  return useMutation({
    mutationFn: (id: string) => apiPost<SimulationRunDetail>(`/api/v1/simulations/${id}/rerun`, {}, once.key()),
    onSuccess: () => {
      once.renew();
      invalidate();
    },
  });
}
