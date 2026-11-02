import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type { ProcurementDepartment, ProcurementSummary, PurchaseOrder, Vendor, VendorInvoice } from "@/types/procurement";

const BASE = "/api/v1/procurement";

export const useProcurementSummary = () =>
  useQuery({ queryKey: ["procurement", "summary"], queryFn: () => apiGet<ProcurementSummary>(`${BASE}/summary/counts`) });
export const useProcurementDepartments = () =>
  useQuery({ queryKey: ["procurement", "departments"], queryFn: () => apiGet<ProcurementDepartment[]>(`${BASE}/departments`) });
export const useVendors = () =>
  useQuery({ queryKey: ["procurement", "vendors"], queryFn: () => apiGet<Page<Vendor>>(`${BASE}/vendors${query({ limit: 25 })}`) });
export const useOrders = () =>
  useQuery({ queryKey: ["procurement", "orders"], queryFn: () => apiGet<Page<PurchaseOrder>>(`${BASE}/orders${query({ limit: 25 })}`) });
export const useInvoices = () =>
  useQuery({ queryKey: ["procurement", "invoices"], queryFn: () => apiGet<Page<VendorInvoice>>(`${BASE}/invoices${query({ limit: 25 })}`) });

function useAction<TBody, TOut>(fn: (body: TBody) => Promise<TOut>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => void client.invalidateQueries({ queryKey: ["procurement"] }) });
}

export const useRegisterVendor = () =>
  useAction((body: { name: string; country: string; category: string; bank_account: string }) => apiPost<Vendor>(`${BASE}/vendors`, body));
export const useDecideVendor = () =>
  useAction(({ id, approve }: { id: string; approve: boolean }) => apiPost<Vendor>(`${BASE}/vendors/${id}/${approve ? "approve" : "reject"}`, {}));
export const useRequestBankChange = () =>
  useAction(({ id, bank_account }: { id: string; bank_account: string }) => apiPost<Vendor>(`${BASE}/vendors/${id}/bank-change`, { bank_account }));
export const useVerifyBankChange = () =>
  useAction(({ id, accept }: { id: string; accept: boolean }) => apiPost<Vendor>(`${BASE}/vendors/${id}/bank-change/${accept ? "verify" : "refuse"}`, {}));
export const useRaiseOrder = () =>
  useAction((body: { vendor_number: string; department_id: string; description: string; lines: { description: string; quantity: number; unit_price: number }[] }) =>
    apiPost<PurchaseOrder>(`${BASE}/orders`, body),
  );
export const useDecideOrder = () =>
  useAction(({ id, approve }: { id: string; approve: boolean }) => apiPost<PurchaseOrder>(`${BASE}/orders/${id}/${approve ? "approve" : "reject"}`, {}));
export const useReceive = () => useAction(({ id, amount }: { id: string; amount: number }) => apiPost<PurchaseOrder>(`${BASE}/orders/${id}/receive`, { amount }));
export const useRecordInvoice = () =>
  useAction((body: { order_number: string; vendor_reference: string; amount: number; invoice_date: string }) => apiPost<VendorInvoice>(`${BASE}/invoices`, body));
export const useDecideInvoice = () =>
  useAction(({ id, pay }: { id: string; pay: boolean }) => apiPost<VendorInvoice>(`${BASE}/invoices/${id}/${pay ? "pay" : "reject"}`, {}));
