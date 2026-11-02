import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type { Candidate, Capacity, Department, HrSummary, LeaveRequest, OnboardingTask, Requisition, Shift } from "@/types/hr";

const BASE = "/api/v1/hr";

function useInvalidate() {
  const client = useQueryClient();
  return () => void client.invalidateQueries({ queryKey: ["hr"] });
}

export const useHrSummary = () => useQuery({ queryKey: ["hr", "summary"], queryFn: () => apiGet<HrSummary>(`${BASE}/summary/counts`) });
export const useDepartments = () => useQuery({ queryKey: ["hr", "departments"], queryFn: () => apiGet<Department[]>(`${BASE}/departments`) });
export const useCapacity = (departmentId: string, on: string) =>
  useQuery({
    queryKey: ["hr", "capacity", departmentId, on],
    queryFn: () => apiGet<Capacity>(`${BASE}/capacity${query({ department_id: departmentId, on })}`),
    enabled: departmentId.length > 0 && on.length > 0,
  });
export const useRequisitions = () =>
  useQuery({ queryKey: ["hr", "requisitions"], queryFn: () => apiGet<Page<Requisition>>(`${BASE}/requisitions${query({ limit: 25 })}`) });
export const useCandidates = () => useQuery({ queryKey: ["hr", "candidates"], queryFn: () => apiGet<Candidate[]>(`${BASE}/candidates`) });
export const useLeave = () => useQuery({ queryKey: ["hr", "leave"], queryFn: () => apiGet<Page<LeaveRequest>>(`${BASE}/leave${query({ limit: 25 })}`) });
export const useShifts = (departmentId: string, on: string) =>
  useQuery({
    queryKey: ["hr", "shifts", departmentId, on],
    queryFn: () => apiGet<Shift[]>(`${BASE}/shifts${query({ department_id: departmentId || undefined, on })}`),
    enabled: on.length > 0,
  });
export const useOnboarding = () => useQuery({ queryKey: ["hr", "onboarding"], queryFn: () => apiGet<OnboardingTask[]>(`${BASE}/onboarding`) });

function useAction<TBody, TOut>(fn: (body: TBody) => Promise<TOut>) {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: fn, onSuccess: invalidate });
}

export const useOpenRequisition = () =>
  useAction((body: { department_id: string; job_title: string; role: string; openings: number; salary_min: number; salary_max: number; reason: string }) =>
    apiPost<Requisition>(`${BASE}/requisitions`, body),
  );
export const useDecideRequisition = () =>
  useAction(({ id, approve }: { id: string; approve: boolean }) => apiPost<Requisition>(`${BASE}/requisitions/${id}/${approve ? "approve" : "cancel"}`, {}));
export const useAddCandidate = () =>
  useAction(({ requisitionId, first_name, last_name }: { requisitionId: string; first_name: string; last_name: string }) =>
    apiPost<Candidate>(`${BASE}/requisitions/${requisitionId}/candidates`, { first_name, last_name }),
  );
export const useOffer = () =>
  useAction(({ id, salary, start_date }: { id: string; salary: number; start_date: string }) => apiPost<Candidate>(`${BASE}/candidates/${id}/offer`, { salary, start_date }));
export const useHire = () => useAction((id: string) => apiPost<Candidate>(`${BASE}/candidates/${id}/hire`, {}));
export const useRequestLeave = () =>
  useAction((body: { employee_number: string; kind: string; start_date: string; end_date: string }) => apiPost<LeaveRequest>(`${BASE}/leave`, body));
export const useDecideLeave = () =>
  useAction(({ id, approve }: { id: string; approve: boolean }) => apiPost<LeaveRequest>(`${BASE}/leave/${id}/${approve ? "approve" : "reject"}`, {}));
export const useLeaveSweep = () => useAction(() => apiPost<{ swept_on: string; on_leave: number; started: number; ended: number }>(`${BASE}/leave/sweep`, {}));
export const useCreateShift = () =>
  useAction((body: { department_id: string; on: string; start_hour: number; hours: number; required: number }) => apiPost<Shift>(`${BASE}/shifts`, body));
export const useAssign = () =>
  useAction(({ id, employee_number }: { id: string; employee_number: string }) => apiPost<Shift>(`${BASE}/shifts/${id}/assign`, { employee_number }));
export const useCompleteTask = () => useAction((id: string) => apiPost<OnboardingTask>(`${BASE}/onboarding/${id}/complete`, {}));
