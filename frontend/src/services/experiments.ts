import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDownload, apiGet, apiPost, query, useIdempotencyKey } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type {
  BenchmarkRow,
  ExperimentCreate,
  ExperimentDetail,
  ExperimentReassessment,
  ExperimentSummary,
  PortfolioCreate,
  PortfolioDetail,
  PortfolioReassessment,
  PortfolioSummary,
  ReEvaluation,
  SeriesCreate,
  SeriesDetail,
  SeriesSummary,
  ThresholdOverview,
  ThresholdProposal,
  ThresholdVersion,
  ReviewerCalibration,
  ReviewObservation,
  ToolComparison,
  ToolComparisonStart,
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
  const once = useIdempotencyKey();
  return useMutation({
    mutationFn: (body: ExperimentCreate) => apiPost<ExperimentDetail>("/api/v1/experiments", body, once.key()),
    onSuccess: () => {
      once.renew();
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

// --- Repeated-seed series (Phase 77) ---------------------------------------------------------

export const useSeriesList = () =>
  useQuery({
    queryKey: ["experiments", "series"],
    queryFn: () => apiGet<Page<SeriesSummary>>(`/api/v1/experiment-series${query({ limit: 20 })}`),
    refetchInterval: (q) => (q.state.data?.items.some((s) => s.status === "running") ? POLL_MS : false),
  });

export const useSeries = (id: string | null) =>
  useQuery({
    queryKey: ["experiments", "series", id],
    queryFn: () => apiGet<SeriesDetail>(`/api/v1/experiment-series/${id}`),
    enabled: Boolean(id),
    refetchInterval: (q) => (q.state.data?.status === "running" ? POLL_MS : false),
  });

export function useCreateSeries() {
  const client = useQueryClient();
  const once = useIdempotencyKey();
  return useMutation({
    mutationFn: (body: SeriesCreate) => apiPost<SeriesDetail>("/api/v1/experiment-series", body, once.key()),
    onSuccess: () => {
      once.renew();
      void client.invalidateQueries({ queryKey: ["experiments"] });
      void client.invalidateQueries({ queryKey: ["simulations"] });
    },
  });
}

// --- Portfolios (Phase 78) -------------------------------------------------------------------

export const usePortfolios = () =>
  useQuery({
    queryKey: ["experiments", "portfolios"],
    queryFn: () => apiGet<Page<PortfolioSummary>>(`/api/v1/experiment-portfolios${query({ limit: 20 })}`),
    refetchInterval: (q) => (q.state.data?.items.some((p) => p.status === "running") ? POLL_MS : false),
  });

export const usePortfolio = (id: string | null) =>
  useQuery({
    queryKey: ["experiments", "portfolios", id],
    queryFn: () => apiGet<PortfolioDetail>(`/api/v1/experiment-portfolios/${id}`),
    enabled: Boolean(id),
    refetchInterval: (q) => (q.state.data?.status === "running" ? POLL_MS : false),
  });

export function useCreatePortfolio() {
  const client = useQueryClient();
  const once = useIdempotencyKey();
  return useMutation({
    mutationFn: (body: PortfolioCreate) => apiPost<PortfolioDetail>("/api/v1/experiment-portfolios", body, once.key()),
    onSuccess: () => {
      once.renew();
      void client.invalidateQueries({ queryKey: ["experiments"] });
      void client.invalidateQueries({ queryKey: ["simulations"] });
    },
  });
}

// --- Scenario thresholds (Phase 80) ----------------------------------------------------------

export const useScenarioThresholds = () =>
  useQuery({
    queryKey: ["experiments", "scenario-thresholds"],
    queryFn: () => apiGet<ThresholdOverview>("/api/v1/scenario-thresholds"),
  });

export function useProposeThresholds() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ThresholdProposal) => apiPost<ThresholdVersion>("/api/v1/scenario-thresholds", body),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["experiments", "scenario-thresholds"] }),
  });
}

export function useDecideThresholds() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decision, note }: { id: string; decision: "approve" | "reject"; note: string }) =>
      apiPost<ThresholdVersion>(`/api/v1/scenario-thresholds/${id}/${decision}`, { note }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["experiments", "scenario-thresholds"] }),
  });
}

export function useExperimentReassessment(id: string) {
  return useMutation({
    mutationFn: () => apiGet<ExperimentReassessment>(`/api/v1/experiments/${id}/under-scenario-thresholds`),
  });
}

export function usePortfolioReassessment(id: string) {
  return useMutation({
    mutationFn: () => apiGet<PortfolioReassessment>(`/api/v1/experiment-portfolios/${id}/under-scenario-thresholds`),
  });
}

// --- Tool comparison (Phase 81) --------------------------------------------------------------

export const useToolComparison = () =>
  useQuery({
    queryKey: ["experiments", "tool-comparison"],
    queryFn: () => apiGet<ToolComparison>("/api/v1/tool-comparison"),
  });

export function useStartComparison() {
  const client = useQueryClient();
  const once = useIdempotencyKey();
  return useMutation({
    mutationFn: (body: ToolComparisonStart) =>
      apiPost<{ series: SeriesSummary[] }>("/api/v1/tool-comparison/runs", body, once.key()),
    onSuccess: () => {
      once.renew();
      void client.invalidateQueries({ queryKey: ["experiments"] });
      void client.invalidateQueries({ queryKey: ["simulations"] });
    },
  });
}

// --- Reviewer calibration (Phase 82) ---------------------------------------------------------

export const useCalibrations = () =>
  useQuery({
    queryKey: ["experiments", "calibrations"],
    queryFn: () => apiGet<ReviewerCalibration[]>("/api/v1/reviewer-calibrations"),
  });

export function useCreateCalibration() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { scenario_id: string; step_id: string; source: string; observations: ReviewObservation[] }) =>
      apiPost<ReviewerCalibration>("/api/v1/reviewer-calibrations", body),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["experiments", "calibrations"] }),
  });
}
