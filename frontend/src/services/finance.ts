import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDownload, apiGet, apiPost, query } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type { CostAllocation, FinanceSummary, JournalLine, ManualJournal, PeriodClose, RegulatoryReport, ReportType } from "@/types/finance";

export const FINANCE_PAGE = 10;

function useInvalidate() {
  const client = useQueryClient();
  return () => void client.invalidateQueries({ queryKey: ["finance"] });
}

function paged<T>(path: string, offset: number) {
  return {
    queryKey: ["finance", path, offset],
    queryFn: () => apiGet<Page<T>>(`/api/v1/finance/${path}${query({ limit: FINANCE_PAGE, offset })}`),
    placeholderData: keepPreviousData,
  };
}

export function useFinanceSummary() {
  return useQuery({ queryKey: ["finance", "summary"], queryFn: () => apiGet<FinanceSummary>("/api/v1/finance/summary/counts") });
}

export const useCloses = (offset = 0) => useQuery(paged<PeriodClose>("closes", offset));
export const useReports = (offset = 0) => useQuery(paged<RegulatoryReport>("reports", offset));
export const useAllocations = (offset = 0) => useQuery(paged<CostAllocation>("allocations", offset));
export const useJournals = (offset = 0) => useQuery(paged<ManualJournal>("journals", offset));

export function usePrepareClose() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (period: string) => apiPost<PeriodClose>("/api/v1/finance/closes", { period }), onSuccess: invalidate });
}

export function useDecideClose() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      apiPost<PeriodClose>(`/api/v1/finance/closes/${id}/${approve ? "approve" : "reject"}`, approve ? {} : { note: "Rejected on review" }),
    onSuccess: invalidate,
  });
}

export function usePrepareReport() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { report_type: ReportType; period: string }) => apiPost<RegulatoryReport>("/api/v1/finance/reports", body),
    onSuccess: invalidate,
  });
}

export function useDecideReport() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, submit }: { id: string; submit: boolean }) =>
      apiPost<RegulatoryReport>(`/api/v1/finance/reports/${id}/${submit ? "submit" : "reject"}`, submit ? {} : { note: "Rejected on review" }),
    onSuccess: invalidate,
  });
}

export async function downloadReportCsv(report: RegulatoryReport) {
  const blob = await apiDownload(`/api/v1/finance/reports/${report.id}/csv`);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${report.report_number}-${report.report_type}-${report.period}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

export function useRecordExpense() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { currency: string; amount: number; description: string }) =>
      apiPost<{ entry_number: string; amount: number; currency: string }>("/api/v1/finance/expenses", body),
    onSuccess: invalidate,
  });
}

export function useCalculateAllocation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { period: string; currency: string }) => apiPost<CostAllocation>("/api/v1/finance/allocations", body),
    onSuccess: invalidate,
  });
}

export function useDecideAllocation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, post }: { id: string; post: boolean }) =>
      apiPost<CostAllocation>(`/api/v1/finance/allocations/${id}/${post ? "post" : "reject"}`, post ? {} : { note: "Rejected on review" }),
    onSuccess: invalidate,
  });
}

export function useProposeJournal() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { currency: string; effective_date: string; description: string; lines: JournalLine[] }) => apiPost<ManualJournal>("/api/v1/finance/journals", body),
    onSuccess: invalidate,
  });
}

export function useDecideJournal() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      apiPost<ManualJournal>(`/api/v1/finance/journals/${id}/${approve ? "approve" : "reject"}`, approve ? {} : { note: "Rejected on review" }),
    onSuccess: invalidate,
  });
}
