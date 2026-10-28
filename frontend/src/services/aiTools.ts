import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPatch, apiPost, query } from "@/services/api";
import type { AiAction, AiAdapter, AiTool, Invocation, ToolCreate } from "@/types/aiTools";
import type { Page } from "@/types/enterprise";
import type { SimulationRunSummary, StartSuite } from "@/types/simulations";

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["ai-tools"] });
    void client.invalidateQueries({ queryKey: ["simulations"] });
  };
}

export const useAiTools = () =>
  useQuery({
    queryKey: ["ai-tools", "list"],
    queryFn: () => apiGet<Page<AiTool>>(`/api/v1/ai-tools${query({ limit: 100 })}`),
  });

export const useAiTool = (id: string | null) =>
  useQuery({
    queryKey: ["ai-tools", "detail", id],
    queryFn: () => apiGet<AiTool>(`/api/v1/ai-tools/${id}`),
    enabled: Boolean(id),
  });

export const useAdapters = () =>
  useQuery({
    queryKey: ["ai-tools", "adapters"],
    queryFn: () => apiGet<AiAdapter[]>("/api/v1/ai-tools/adapters"),
    staleTime: Infinity,
  });

export const useActions = () =>
  useQuery({
    queryKey: ["ai-tools", "actions"],
    queryFn: () => apiGet<AiAction[]>("/api/v1/ai-tools/actions"),
    staleTime: Infinity,
  });

export const useInvocations = (tool: string | null, offset: number, limit: number) =>
  useQuery({
    queryKey: ["ai-tools", "invocations", tool, offset, limit],
    queryFn: () =>
      apiGet<Page<Invocation>>(`/api/v1/ai-tools/invocations${query({ tool, offset, limit })}`),
    enabled: Boolean(tool),
    placeholderData: keepPreviousData,
  });

export const useSuiteRuns = (batchId: string | null) =>
  useQuery({
    queryKey: ["simulations", "suite", batchId],
    queryFn: () =>
      apiGet<Page<SimulationRunSummary>>(`/api/v1/simulations${query({ batch_id: batchId, limit: 10 })}`),
    enabled: Boolean(batchId),
    refetchInterval: (q) =>
      q.state.data?.items.some((r) => r.status === "queued" || r.status === "running") ? 2000 : false,
  });

export function useRegisterTool() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: ToolCreate) => apiPost<AiTool>("/api/v1/ai-tools", body),
    onSuccess: invalidate,
  });
}

export function useSetToolStatus() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: "active" | "disabled" }) =>
      apiPatch<AiTool>(`/api/v1/ai-tools/${id}`, { status }),
    onSuccess: invalidate,
  });
}

export function useInvokeTool(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { action: string; input: Record<string, unknown> }) =>
      apiPost<Invocation>(`/api/v1/ai-tools/${id}/invoke`, body),
    onSettled: invalidate,
  });
}

export function useStartSuite() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: StartSuite) => apiPost<SimulationRunSummary[]>("/api/v1/simulations/suites", body),
    onSuccess: invalidate,
  });
}
