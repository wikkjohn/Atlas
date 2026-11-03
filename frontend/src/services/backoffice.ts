import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { DepartmentRequest, ThinDepartment } from "@/types/backoffice";
import type { Page } from "@/types/enterprise";

const BASE = "/api/v1/backoffice";

export const useThinDepartments = () => useQuery({ queryKey: ["backoffice", "departments"], queryFn: () => apiGet<ThinDepartment[]>(`${BASE}/departments`) });
export const useDepartmentRequests = (department: string) =>
  useQuery({
    queryKey: ["backoffice", "requests", department],
    queryFn: () => apiGet<Page<DepartmentRequest>>(`${BASE}/requests${query({ department, limit: 25 })}`),
    enabled: department.length > 0,
  });

function useAction<TBody, TOut>(fn: (body: TBody) => Promise<TOut>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => void client.invalidateQueries({ queryKey: ["backoffice"] }) });
}

export const useSubmitRequest = () =>
  useAction((body: { department: string; process: string; title: string; details: string; amount?: number }) => apiPost<DepartmentRequest>(`${BASE}/requests`, body));
export const useDecideRequest = () =>
  useAction(({ id, approve, note }: { id: string; approve: boolean; note?: string }) => apiPost<DepartmentRequest>(`${BASE}/requests/${id}/${approve ? "approve" : "reject"}`, { note }));
export const useCompleteRequest = () => useAction((id: string) => apiPost<DepartmentRequest>(`${BASE}/requests/${id}/complete`, {}));
