import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDownload, apiGet, apiPost, query } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type {
  BenchmarkRow,
  ExperimentCreate,
  ExperimentDetail,
  ExperimentSummary,
  ReEvaluation,
} from "@/types/experiments";

const POLL_MS = 2000;

export const useExperiments = (offset: number, limit: number) =>
  useQuery({
    queryKey: ["experiments", "list", offset, limit],
    queryFn: () => apiGet<Page<ExperimentSummary>>(`/api/v1/experiments${query({ offset, limit })}`),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((e) => e.status === "running") ? POLL_MS : false),
  });

export const useExperiment = (id: string | null) =>
  useQuery({
    queryKey: ["experiments", "detail", id],
    queryFn: () => apiGet<ExperimentDetail>(`/api/v1/experiments/${id}`),
    enabled: Boolean(id),
    refetchInterval: (q) => (q.state.data?.status === "running" ? POLL_MS : false),
  });

export const useBenchmarks = () =>
  useQuery({
    queryKey: ["experiments", "benchmarks"],
    queryFn: () => apiGet<BenchmarkRow[]>("/api/v1/benchmarks"),
  });

export function useCreateExperiment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ExperimentCreate) => apiPost<ExperimentDetail>("/api/v1/experiments", body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["experiments"] });
      void client.invalidateQueries({ queryKey: ["simulations"] });
    },
  });
}

export function useReEvaluate(id: string) {
  return useMutation({
    mutationFn: () => apiPost<ReEvaluation>(`/api/v1/experiments/${id}/re-evaluate`, {}),
  });
}

/** Download the experiment's report through the authenticated API. */
export async function downloadReport(id: string, number: number, format: "markdown" | "json") {
  const blob = await apiDownload(`/api/v1/experiments/${id}/report${query({ format })}`);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `atlas-experiment-${number}.${format === "json" ? "json" : "md"}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
