import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type { Application, ApplicationDetail, ChangeRequest, EstateSummary, Incident, ItopsSummary } from "@/types/itops";

const BASE = "/api/v1/itops";

export const useItopsSummary = () => useQuery({ queryKey: ["itops", "summary"], queryFn: () => apiGet<ItopsSummary>(`${BASE}/summary/counts`) });
/** Applications for the forms: the bank's own catalogue, not the generated estate (an API page holds at most 200). */
export const useApplications = () =>
  useQuery({
    queryKey: ["itops", "applications", "choices"],
    queryFn: () => apiGet<Page<Application>>(`${BASE}/applications${query({ generated: false, limit: 200 })}`),
  });
export const useRegistry = (filters: { q: string; tier: string; offset: number }) =>
  useQuery({
    queryKey: ["itops", "registry", filters],
    queryFn: () => apiGet<Page<Application>>(`${BASE}/applications${query({ q: filters.q || undefined, tier: filters.tier || undefined, limit: 25, offset: filters.offset })}`),
  });
export const useApplicationDetail = (id: string) =>
  useQuery({ queryKey: ["itops", "application", id], queryFn: () => apiGet<ApplicationDetail>(`${BASE}/applications/${id}`), enabled: id.length > 0 });
export const useEstateSummary = () => useQuery({ queryKey: ["itops", "estate"], queryFn: () => apiGet<EstateSummary>(`${BASE}/estate/summary`) });
export const useIncidents = () =>
  useQuery({ queryKey: ["itops", "incidents"], queryFn: () => apiGet<Page<Incident>>(`${BASE}/incidents${query({ limit: 25 })}`) });
export const useChanges = () =>
  useQuery({ queryKey: ["itops", "changes"], queryFn: () => apiGet<Page<ChangeRequest>>(`${BASE}/changes${query({ limit: 25 })}`) });

function useAction<TBody, TOut>(fn: (body: TBody) => Promise<TOut>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => void client.invalidateQueries({ queryKey: ["itops"] }) });
}

export const useOpenIncident = () =>
  useAction((body: { application_number: string; title: string; impact: string; urgency: string }) => apiPost<Incident>(`${BASE}/incidents`, body));
export const useAcknowledge = () => useAction((id: string) => apiPost<Incident>(`${BASE}/incidents/${id}/acknowledge`, {}));
export const useResolve = () =>
  useAction(({ id, resolution, change_number }: { id: string; resolution: string; change_number?: string }) =>
    apiPost<Incident>(`${BASE}/incidents/${id}/resolve`, { resolution, change_number: change_number || undefined }),
  );
export const useCloseIncident = () => useAction(({ id, review }: { id: string; review?: string }) => apiPost<Incident>(`${BASE}/incidents/${id}/close`, { review: review || undefined }));
export const useSweep = () => useAction(() => apiPost<{ response_breaches: number; resolution_breaches: number }>(`${BASE}/incidents/sweep`, {}));
export const useRaiseChange = () =>
  useAction((body: { application_number: string; title: string; kind: string; backout_plan: string; planned_start: string; planned_end: string; incident_number?: string }) =>
    apiPost<ChangeRequest>(`${BASE}/changes`, body),
  );
export const useDecideChange = () =>
  useAction(({ id, approve }: { id: string; approve: boolean }) => apiPost<ChangeRequest>(`${BASE}/changes/${id}/${approve ? "approve" : "reject"}`, {}));
export const useImplement = () => useAction(({ id, success }: { id: string; success: boolean }) => apiPost<ChangeRequest>(`${BASE}/changes/${id}/implement`, { success }));
export const useGenerateEstate = () =>
  useAction((body: { count: number; seed: number }) => apiPost<{ created: number; existing: number; dependencies_added: number; seconds: number }>(`${BASE}/estate/generate`, body));

