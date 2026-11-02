import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPut, query } from "@/services/api";
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
export const useWorkflows = (q) => useQuery({
    queryKey: ["workflows", "list", q],
    queryFn: () => apiGet(`/api/v1/workflows${query({ q, limit: CATALOGUE_LIMIT })}`),
});
/** Catalogue search (Phase 22): free text and one value per facet, with facet counts. */
export const useCatalogue = (filters) => useQuery({
    queryKey: ["workflows", "catalogue", filters],
    queryFn: () => apiGet(`/api/v1/workflow-catalogue${query({ ...filters, limit: CATALOGUE_LIMIT })}`),
    placeholderData: keepPreviousData,
});
export function useClassify(workflowId) {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPut(`/api/v1/workflow-catalogue/${workflowId}`, body),
        onSuccess: invalidate,
    });
}
export const useWorkflowDefinition = (id, version) => useQuery({
    queryKey: ["workflows", "definition", id, version],
    queryFn: () => apiGet(`/api/v1/workflows/${id}${query({ version })}`),
    enabled: Boolean(id),
});
export const useWorkflowMetrics = (id) => useQuery({
    queryKey: ["workflows", "metrics", id],
    queryFn: () => apiGet(`/api/v1/workflows/${id}/metrics`),
    enabled: Boolean(id),
});
export const useExecutions = (params) => useQuery({
    queryKey: ["workflow-executions", "list", params],
    queryFn: () => apiGet(`/api/v1/workflow-executions${query(params)}`),
    placeholderData: keepPreviousData,
});
export const useExecution = (id) => useQuery({
    queryKey: ["workflow-executions", "detail", id],
    queryFn: () => apiGet(`/api/v1/workflow-executions/${id}`),
    enabled: Boolean(id),
});
export const useExecutionHistory = (id) => useQuery({
    queryKey: ["workflow-executions", "history", id],
    queryFn: () => apiGet(`/api/v1/workflow-executions/${id}/history`),
    enabled: Boolean(id),
});
export const useTasks = (actionable) => useQuery({
    queryKey: ["workflow-tasks", actionable],
    queryFn: () => apiGet(`/api/v1/workflow-tasks${query({ actionable, limit: 100 })}`),
});
export function useStartExecution(workflowId) {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ input, idempotencyKey }) => apiPost(`/api/v1/workflows/${workflowId}/executions`, { input }, idempotencyKey),
        onSuccess: invalidate,
    });
}
export function useCompleteTask() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ runId, decision, note }) => apiPost(`/api/v1/workflow-tasks/${runId}/complete`, { decision, note: note || null }),
        onSuccess: invalidate,
    });
}
export function useSignal(executionId) {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ signal, payload }) => apiPost(`/api/v1/workflow-executions/${executionId}/signals`, { signal, payload }),
        onSuccess: invalidate,
    });
}
/** Synthetic document numbers: prefix, 7 digits and a check digit (sum of digits mod 10). */
export function syntheticDocumentNumber(kind) {
    const prefix = { passport: "P", national_id: "N", proof_of_address: "A" }[kind];
    const body = String(Math.floor(Math.random() * 10_000_000)).padStart(7, "0");
    const check = [...body].reduce((sum, d) => sum + Number(d), 0) % 10;
    return `${prefix}${body}${check}`;
}
// --- Stored definitions (Phase 17) ----------------------------------------------------------
export const useStoredVersions = (workflowId) => useQuery({
    queryKey: ["workflow-definitions", "versions", workflowId],
    queryFn: () => apiGet(`/api/v1/workflow-definitions${query({ workflow_id: workflowId })}`),
    enabled: Boolean(workflowId),
});
export const useLibraryHandlers = (enabled = true) => useQuery({
    queryKey: ["workflow-definitions", "handlers"],
    queryFn: () => apiGet("/api/v1/workflow-definitions/handlers"),
    staleTime: Infinity,
    enabled,
});
export const exportDefinition = (workflowId, version) => apiGet(`/api/v1/workflows/${workflowId}/export${query({ version })}`);
export const useValidateDefinition = () => useMutation({
    mutationFn: (definition) => apiPost("/api/v1/workflow-definitions/validate", { definition }),
});
export function useImportDefinition() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (definition) => apiPost("/api/v1/workflow-definitions", { definition }),
        onSuccess: invalidate,
    });
}
export function useSetDefinitionStatus() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ workflowId, version, action, note }) => apiPost(`/api/v1/workflow-definitions/${workflowId}/versions/${version}/${action}`, action === "approve" || action === "return" ? { note: note || null } : {}),
        onSuccess: invalidate,
    });
}
// --- Templates (Phase 19) -------------------------------------------------------------------
export const useTemplates = () => useQuery({
    queryKey: ["workflow-templates", "list"],
    queryFn: () => apiGet("/api/v1/workflow-templates"),
});
export const useTemplateVariants = (templateId) => useQuery({
    queryKey: ["workflow-templates", "variants", templateId],
    queryFn: () => apiGet(`/api/v1/workflow-templates/${templateId}/variants`),
    enabled: Boolean(templateId),
});
export function useGenerateVariants(templateId) {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (spec) => apiPost(`/api/v1/workflow-templates/${templateId}/generate`, spec),
        onSuccess: (result) => {
            if (result.stored)
                invalidate();
        },
    });
}
// --- Generated tests (Phase 20) -------------------------------------------------------------
export const useTestRuns = (workflowId, enabled = true) => useQuery({
    queryKey: ["workflow-definitions", "tests", workflowId],
    queryFn: () => apiGet(`/api/v1/workflow-definitions/${workflowId}/tests`),
    enabled: Boolean(workflowId) && enabled,
});
export function useRunTests() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ workflowId, version }) => apiPost(`/api/v1/workflow-definitions/${workflowId}/versions/${version}/tests`, {}),
        onSuccess: invalidate,
    });
}
// --- Graph and editor preview (Phase 21) ----------------------------------------------------
export const useWorkflowGraph = (workflowId, version, enabled = true) => useQuery({
    queryKey: ["workflows", "graph", workflowId, version],
    queryFn: () => apiGet(`/api/v1/workflows/${workflowId}/graph${query({ version })}`),
    enabled: Boolean(workflowId) && enabled,
});
export const previewDefinition = (definition) => apiPost("/api/v1/workflow-definitions/preview", { definition });
