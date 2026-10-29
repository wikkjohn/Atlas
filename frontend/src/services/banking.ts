import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query, useIdempotencyKey } from "@/services/api";
import type {
  Account,
  AccountRequest,
  Customer,
  Eligibility,
  Instalment,
  JournalEntry,
  LedgerAccount,
  Loan,
  MovementResult,
  Payment,
  PayoffQuote,
  ReconciliationMode,
  ReconciliationReport,
  ReconciliationRun,
  ServicingRun,
  StatementLine,
} from "@/types/banking";
import type { Page } from "@/types/enterprise";

type Params = Record<string, string | number | boolean | null | undefined>;

/** Everything a banking change can affect. */
function useInvalidateBanking() {
  const client = useQueryClient();
  return () => {
    for (const key of ["customers", "accounts", "account-requests", "ledger", "payments", "loans"]) {
      void client.invalidateQueries({ queryKey: [key] });
    }
  };
}

// --- Customers ---------------------------------------------------------------------------

export function useCustomers(params: Params) {
  return useQuery({
    queryKey: ["customers", "list", params],
    queryFn: () => apiGet<Page<Customer>>(`/api/v1/customers${query(params)}`),
    placeholderData: keepPreviousData,
  });
}

export function useCustomer(id: string | null) {
  return useQuery({
    queryKey: ["customers", "detail", id],
    queryFn: () => apiGet<Customer>(`/api/v1/customers/${id}`),
    enabled: Boolean(id),
  });
}

export function useCreateCustomer() {
  const invalidate = useInvalidateBanking();
  return useMutation({
    mutationFn: (body: unknown) => apiPost<Customer>("/api/v1/customers", body),
    onSuccess: invalidate,
  });
}

export function useReviewCustomer(id: string) {
  const invalidate = useInvalidateBanking();
  return useMutation({
    mutationFn: (body: unknown) => apiPost<Customer>(`/api/v1/customers/${id}/review`, body),
    onSuccess: invalidate,
  });
}

export function useEligibility(customerId: string | null, accountType: string | null) {
  return useQuery({
    queryKey: ["customers", "eligibility", customerId, accountType],
    queryFn: () =>
      apiGet<Eligibility>(
        `/api/v1/customers/${customerId}/eligibility${query({ account_type: accountType })}`,
      ),
    enabled: Boolean(customerId && accountType),
  });
}

// --- Account requests ----------------------------------------------------------------------

export function useAccountRequests(params: Params, enabled = true) {
  return useQuery({
    queryKey: ["account-requests", params],
    queryFn: () => apiGet<Page<AccountRequest>>(`/api/v1/account-requests${query(params)}`),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useSubmitAccountRequest() {
  const invalidate = useInvalidateBanking();
  return useMutation({
    mutationFn: (body: unknown) => apiPost<AccountRequest>("/api/v1/account-requests", body),
    onSuccess: invalidate,
  });
}

export function useDecideRequest() {
  const invalidate = useInvalidateBanking();
  return useMutation({
    mutationFn: ({ id, decision, body }: { id: string; decision: "approve" | "reject"; body: unknown }) =>
      apiPost<unknown>(`/api/v1/account-requests/${id}/${decision}`, body),
    onSuccess: invalidate,
  });
}

// --- Accounts ------------------------------------------------------------------------------

export function useAccounts(params: Params, enabled = true) {
  return useQuery({
    queryKey: ["accounts", "list", params],
    queryFn: () => apiGet<Page<Account>>(`/api/v1/accounts${query(params)}`),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useAccount(id: string | null) {
  return useQuery({
    queryKey: ["accounts", "detail", id],
    queryFn: () => apiGet<Account>(`/api/v1/accounts/${id}`),
    enabled: Boolean(id),
  });
}

export function useTransactions(id: string | null) {
  return useQuery({
    queryKey: ["accounts", "transactions", id],
    queryFn: () => apiGet<Page<StatementLine>>(`/api/v1/accounts/${id}/transactions?limit=50`),
    enabled: Boolean(id),
  });
}

/** Deposit or withdraw. The caller supplies the idempotency key so a retry reuses it. */
export function useMovement(accountId: string) {
  const invalidate = useInvalidateBanking();
  return useMutation({
    mutationFn: ({
      kind,
      amount,
      memo,
      idempotencyKey,
    }: {
      kind: "deposits" | "withdrawals";
      amount: number;
      memo?: string;
      idempotencyKey: string;
    }) =>
      apiPost<MovementResult>(
        `/api/v1/accounts/${accountId}/${kind}`,
        { amount, memo: memo || null },
        idempotencyKey,
      ),
    onSuccess: invalidate,
  });
}

export function useAccountStatus(accountId: string) {
  const invalidate = useInvalidateBanking();
  return useMutation({
    mutationFn: ({ action, reason }: { action: "freeze" | "unfreeze" | "close"; reason: string }) =>
      apiPost<Account>(`/api/v1/accounts/${accountId}/${action}`, { reason }),
    onSuccess: invalidate,
  });
}

// --- Ledger --------------------------------------------------------------------------------

export function useLedgerAccounts(params: Params, enabled = true) {
  return useQuery({
    queryKey: ["ledger", "accounts", params],
    queryFn: () => apiGet<Page<LedgerAccount>>(`/api/v1/ledger/accounts${query(params)}`),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useJournalEntries(params: Params, enabled = true) {
  return useQuery({
    queryKey: ["ledger", "entries", params],
    queryFn: () => apiGet<Page<JournalEntry>>(`/api/v1/ledger/journal-entries${query(params)}`),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useReconciliation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (mode: ReconciliationMode) =>
      apiPost<ReconciliationReport>(`/api/v1/ledger/reconciliation${query({ mode })}`, {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["ledger", "reconciliations"] }),
  });
}

export function useReconciliationRuns(limit = 10) {
  return useQuery({
    queryKey: ["ledger", "reconciliations", limit],
    queryFn: () => apiGet<Page<ReconciliationRun>>(`/api/v1/ledger/reconciliations${query({ limit })}`),
  });
}

// --- Payments and loans (Phase 9) ------------------------------------------------------------

export function usePayments(params: Params) {
  return useQuery({
    queryKey: ["payments", params],
    queryFn: () => apiGet<Page<Payment>>(`/api/v1/payments${query(params)}`),
    placeholderData: keepPreviousData,
  });
}

export function useLoans(params: Params) {
  return useQuery({
    queryKey: ["loans", params],
    queryFn: () => apiGet<Page<Loan>>(`/api/v1/loans${query(params)}`),
    placeholderData: keepPreviousData,
  });
}

// --- Loan servicing (Phase 10) ---------------------------------------------------------------

export function useLoan(id: string | null) {
  return useQuery({
    queryKey: ["loans", "detail", id],
    queryFn: () => apiGet<Loan>(`/api/v1/loans/${id}`),
    enabled: Boolean(id),
  });
}

export function useLoanSchedule(id: string | null) {
  return useQuery({
    queryKey: ["loans", "schedule", id],
    queryFn: () => apiGet<Instalment[]>(`/api/v1/loans/${id}/schedule`),
    enabled: Boolean(id),
  });
}

export function usePayoffQuote(id: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["loans", "payoff-quote", id],
    queryFn: () => apiGet<PayoffQuote>(`/api/v1/loans/${id}/payoff-quote`),
    enabled: Boolean(id) && enabled,
  });
}

/** Money movements keep one Idempotency-Key until they succeed, so a retry never pays twice. */
function useLoanPayment<Body>(path: (id: string) => string) {
  const invalidate = useInvalidateBanking();
  const client = useQueryClient();
  const once = useIdempotencyKey();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Body }) => apiPost<Loan>(path(id), body, once.key()),
    onSuccess: () => {
      once.renew();
      invalidate();
      // Repayments and servicing runs open and close collections cases (WF-0004).
      for (const key of ["workflow-executions", "workflow-tasks"]) void client.invalidateQueries({ queryKey: [key] });
    },
  });
}

export const useRepayArrears = () =>
  useLoanPayment<{ instalments?: number }>((id) => `/api/v1/loans/${id}/repayments`);

export const usePayOffLoan = () => useLoanPayment<Record<string, never>>((id) => `/api/v1/loans/${id}/payoff`);

export function useServicingRuns(params: Params) {
  return useQuery({
    queryKey: ["loans", "servicing-runs", params],
    queryFn: () => apiGet<Page<ServicingRun>>(`/api/v1/loans/servicing-runs${query(params)}`),
    placeholderData: keepPreviousData,
  });
}

export function useRunServicing() {
  const invalidate = useInvalidateBanking();
  const client = useQueryClient();
  const once = useIdempotencyKey();
  return useMutation({
    mutationFn: (asOf: string) => apiPost<ServicingRun>("/api/v1/loans/servicing-runs", { as_of: asOf }, once.key()),
    onSuccess: () => {
      once.renew();
      invalidate();
      // Repayments and servicing runs open and close collections cases (WF-0004).
      for (const key of ["workflow-executions", "workflow-tasks"]) void client.invalidateQueries({ queryKey: [key] });
    },
  });
}
