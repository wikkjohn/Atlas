import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { WorkflowGraphData } from "@/features/workflows/WorkflowGraph";
import type { Page } from "@/types/enterprise";
import type {
  DraftPreview,
  ExecutionDetail,
  ExecutionSummary,
  GenerationResult,
  GenerationSpec,
  ImportResult,
  LibraryHandler,
  StoredDefinition,
  TestRun,
  ValidationReport,
  WorkflowDefinition,
  WorkflowEvent,
  WorkflowMetrics,
  WorkflowSummary,
  WorkflowTask,
  WorkflowTemplate,
  WorkflowVariant,
} from "@/types/workflows";

type Params = Record<string, string | number | boolean | null | undefined>;

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    for (const key of ["workflows", "workflow-definitions", "workflow-templates", "workflow-executions", "workflow-tasks", "customers", "accounts", "payments", "loans"]) {
      void client.invalidateQueries({ queryKey: [key] });
    }
  };
}

/** The catalogue is capped: thousands of generated variants are found by searching. */
export const CATALOGUE_LIMIT = 200;

export const useWorkflows = (q?: string) =>
  useQuery({
    queryKey: ["workflows", "list", q],
    queryFn: () => apiGet<WorkflowSummary[]>(`/api/v1/workflows${query({ q, limit: CATALOGUE_LIMIT })}`),
  });

export const useWorkflowDefinition = (id: string | null) =>
  useQuery({
    queryKey: ["workflows", "definition", id],
    queryFn: () => apiGet<WorkflowDefinition>(`/api/v1/workflows/${id}`),
    enabled: Boolean(id),
  });

export const useWorkflowMetrics = (id: string | null) =>
  useQuery({
    queryKey: ["workflows", "metrics", id],
    queryFn: () => apiGet<WorkflowMetrics>(`/api/v1/workflows/${id}/metrics`),
    enabled: Boolean(id),
  });

export const useExecutions = (params: Params) =>
  useQuery({
    queryKey: ["workflow-executions", "list", params],
    queryFn: () => apiGet<Page<ExecutionSummary>>(`/api/v1/workflow-executions${query(params)}`),
    placeholderData: keepPreviousData,
  });

export const useExecution = (id: string | null) =>
  useQuery({
    queryKey: ["workflow-executions", "detail", id],
    queryFn: () => apiGet<ExecutionDetail>(`/api/v1/workflow-executions/${id}`),
    enabled: Boolean(id),
  });

export const useExecutionHistory = (id: string | null) =>
  useQuery({
    queryKey: ["workflow-executions", "history", id],
    queryFn: () => apiGet<WorkflowEvent[]>(`/api/v1/workflow-executions/${id}/history`),
    enabled: Boolean(id),
  });

export const useTasks = (actionable: boolean) =>
  useQuery({
    queryKey: ["workflow-tasks", actionable],
    queryFn: () => apiGet<Page<WorkflowTask>>(`/api/v1/workflow-tasks${query({ actionable, limit: 100 })}`),
  });

export function useStartExecution(workflowId: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ input, idempotencyKey }: { input: unknown; idempotencyKey: string }) =>
      apiPost<ExecutionDetail>(`/api/v1/workflows/${workflowId}/executions`, { input }, idempotencyKey),
    onSuccess: invalidate,
  });
}

export function useCompleteTask() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ runId, decision, note }: { runId: string; decision: "approve" | "reject"; note?: string }) =>
      apiPost<ExecutionDetail>(`/api/v1/workflow-tasks/${runId}/complete`, { decision, note: note || null }),
    onSuccess: invalidate,
  });
}

export function useSignal(executionId: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ signal, payload }: { signal: string; payload: Record<string, unknown> }) =>
      apiPost<ExecutionDetail>(`/api/v1/workflow-executions/${executionId}/signals`, { signal, payload }),
    onSuccess: invalidate,
  });
}

/** Synthetic document numbers: prefix, 7 digits and a check digit (sum of digits mod 10). */
export function syntheticDocumentNumber(kind: "passport" | "national_id" | "proof_of_address"): string {
  const prefix = { passport: "P", national_id: "N", proof_of_address: "A" }[kind];
  const body = String(Math.floor(Math.random() * 10_000_000)).padStart(7, "0");
  const check = [...body].reduce((sum, d) => sum + Number(d), 0) % 10;
  return `${prefix}${body}${check}`;
}

// --- Stored definitions (Phase 17) ----------------------------------------------------------

export const useStoredDefinitions = () =>
  useQuery({
    queryKey: ["workflow-definitions", "list"],
    queryFn: () => apiGet<StoredDefinition[]>("/api/v1/workflow-definitions"),
  });

export const useLibraryHandlers = (enabled = true) =>
  useQuery({
    queryKey: ["workflow-definitions", "handlers"],
    queryFn: () => apiGet<LibraryHandler[]>("/api/v1/workflow-definitions/handlers"),
    staleTime: Infinity,
    enabled,
  });

export const exportDefinition = (workflowId: string, version?: number) =>
  apiGet<Record<string, unknown>>(`/api/v1/workflows/${workflowId}/export${query({ version })}`);

export const useValidateDefinition = () =>
  useMutation({
    mutationFn: (definition: unknown) =>
      apiPost<ValidationReport>("/api/v1/workflow-definitions/validate", { definition }),
  });

export function useImportDefinition() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (definition: unknown) =>
      apiPost<ImportResult>("/api/v1/workflow-definitions", { definition }),
    onSuccess: invalidate,
  });
}

export function useSetDefinitionStatus() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ workflowId, version, action }: { workflowId: string; version: number; action: "retire" | "reactivate" }) =>
      apiPost<StoredDefinition>(`/api/v1/workflow-definitions/${workflowId}/versions/${version}/${action}`, {}),
    onSuccess: invalidate,
  });
}

// --- Templates (Phase 19) -------------------------------------------------------------------

export const useTemplates = () =>
  useQuery({
    queryKey: ["workflow-templates", "list"],
    queryFn: () => apiGet<WorkflowTemplate[]>("/api/v1/workflow-templates"),
  });

export const useTemplateVariants = (templateId: string | null) =>
  useQuery({
    queryKey: ["workflow-templates", "variants", templateId],
    queryFn: () => apiGet<WorkflowVariant[]>(`/api/v1/workflow-templates/${templateId}/variants`),
    enabled: Boolean(templateId),
  });

export function useGenerateVariants(templateId: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (spec: GenerationSpec) =>
      apiPost<GenerationResult>(`/api/v1/workflow-templates/${templateId}/generate`, spec),
    onSuccess: (result) => {
      if (result.stored) invalidate();
    },
  });
}

// --- Generated tests (Phase 20) -------------------------------------------------------------

export const useTestRuns = (workflowId: string | null, enabled = true) =>
  useQuery({
    queryKey: ["workflow-definitions", "tests", workflowId],
    queryFn: () => apiGet<TestRun[]>(`/api/v1/workflow-definitions/${workflowId}/tests`),
    enabled: Boolean(workflowId) && enabled,
  });

export function useRunTests() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ workflowId, version }: { workflowId: string; version: number }) =>
      apiPost<TestRun>(`/api/v1/workflow-definitions/${workflowId}/versions/${version}/tests`, {}),
    onSuccess: invalidate,
  });
}

// --- Graph and editor preview (Phase 21) ----------------------------------------------------

export const useWorkflowGraph = (workflowId: string | null, version?: number, enabled = true) =>
  useQuery({
    queryKey: ["workflows", "graph", workflowId, version],
    queryFn: () => apiGet<WorkflowGraphData>(`/api/v1/workflows/${workflowId}/graph${query({ version })}`),
    enabled: Boolean(workflowId) && enabled,
  });

export const previewDefinition = (definition: unknown) =>
  apiPost<DraftPreview>("/api/v1/workflow-definitions/preview", { definition });
