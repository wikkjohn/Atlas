import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query, useIdempotencyKey } from "@/services/api";
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
export function useCustomers(params) {
    return useQuery({
        queryKey: ["customers", "list", params],
        queryFn: () => apiGet(`/api/v1/customers${query(params)}`),
        placeholderData: keepPreviousData,
    });
}
export function useCustomer(id) {
    return useQuery({
        queryKey: ["customers", "detail", id],
        queryFn: () => apiGet(`/api/v1/customers/${id}`),
        enabled: Boolean(id),
    });
}
export function useCreateCustomer() {
    const invalidate = useInvalidateBanking();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/customers", body),
        onSuccess: invalidate,
    });
}
export function useReviewCustomer(id) {
    const invalidate = useInvalidateBanking();
    return useMutation({
        mutationFn: (body) => apiPost(`/api/v1/customers/${id}/review`, body),
        onSuccess: invalidate,
    });
}
export function useEligibility(customerId, accountType) {
    return useQuery({
        queryKey: ["customers", "eligibility", customerId, accountType],
        queryFn: () => apiGet(`/api/v1/customers/${customerId}/eligibility${query({ account_type: accountType })}`),
        enabled: Boolean(customerId && accountType),
    });
}
// --- Account requests ----------------------------------------------------------------------
export function useAccountRequests(params, enabled = true) {
    return useQuery({
        queryKey: ["account-requests", params],
        queryFn: () => apiGet(`/api/v1/account-requests${query(params)}`),
        placeholderData: keepPreviousData,
        enabled,
    });
}
export function useSubmitAccountRequest() {
    const invalidate = useInvalidateBanking();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/account-requests", body),
        onSuccess: invalidate,
    });
}
export function useDecideRequest() {
    const invalidate = useInvalidateBanking();
    return useMutation({
        mutationFn: ({ id, decision, body }) => apiPost(`/api/v1/account-requests/${id}/${decision}`, body),
        onSuccess: invalidate,
    });
}
// --- Accounts ------------------------------------------------------------------------------
export function useAccounts(params, enabled = true) {
    return useQuery({
        queryKey: ["accounts", "list", params],
        queryFn: () => apiGet(`/api/v1/accounts${query(params)}`),
        placeholderData: keepPreviousData,
        enabled,
    });
}
export function useAccount(id) {
    return useQuery({
        queryKey: ["accounts", "detail", id],
        queryFn: () => apiGet(`/api/v1/accounts/${id}`),
        enabled: Boolean(id),
    });
}
export function useTransactions(id) {
    return useQuery({
        queryKey: ["accounts", "transactions", id],
        queryFn: () => apiGet(`/api/v1/accounts/${id}/transactions?limit=50`),
        enabled: Boolean(id),
    });
}
/** Deposit or withdraw. The caller supplies the idempotency key so a retry reuses it. */
export function useMovement(accountId) {
    const invalidate = useInvalidateBanking();
    return useMutation({
        mutationFn: ({ kind, amount, memo, idempotencyKey, }) => apiPost(`/api/v1/accounts/${accountId}/${kind}`, { amount, memo: memo || null }, idempotencyKey),
        onSuccess: invalidate,
    });
}
export function useAccountStatus(accountId) {
    const invalidate = useInvalidateBanking();
    return useMutation({
        mutationFn: ({ action, reason }) => apiPost(`/api/v1/accounts/${accountId}/${action}`, { reason }),
        onSuccess: invalidate,
    });
}
// --- Ledger --------------------------------------------------------------------------------
export function useLedgerAccounts(params, enabled = true) {
    return useQuery({
        queryKey: ["ledger", "accounts", params],
        queryFn: () => apiGet(`/api/v1/ledger/accounts${query(params)}`),
        placeholderData: keepPreviousData,
        enabled,
    });
}
export function useJournalEntries(params, enabled = true) {
    return useQuery({
        queryKey: ["ledger", "entries", params],
        queryFn: () => apiGet(`/api/v1/ledger/journal-entries${query(params)}`),
        placeholderData: keepPreviousData,
        enabled,
    });
}
export function useReconciliation() {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (mode) => apiPost(`/api/v1/ledger/reconciliation${query({ mode })}`, {}),
        onSuccess: () => void client.invalidateQueries({ queryKey: ["ledger", "reconciliations"] }),
    });
}
export function useReconciliationRuns(limit = 10) {
    return useQuery({
        queryKey: ["ledger", "reconciliations", limit],
        queryFn: () => apiGet(`/api/v1/ledger/reconciliations${query({ limit })}`),
    });
}
// --- Payments and loans (Phase 9) ------------------------------------------------------------
export function usePayments(params) {
    return useQuery({
        queryKey: ["payments", params],
        queryFn: () => apiGet(`/api/v1/payments${query(params)}`),
        placeholderData: keepPreviousData,
    });
}
export function useLoans(params) {
    return useQuery({
        queryKey: ["loans", params],
        queryFn: () => apiGet(`/api/v1/loans${query(params)}`),
        placeholderData: keepPreviousData,
    });
}
// --- Loan servicing (Phase 10) ---------------------------------------------------------------
export function useLoan(id) {
    return useQuery({
        queryKey: ["loans", "detail", id],
        queryFn: () => apiGet(`/api/v1/loans/${id}`),
        enabled: Boolean(id),
    });
}
export function useLoanSchedule(id) {
    return useQuery({
        queryKey: ["loans", "schedule", id],
        queryFn: () => apiGet(`/api/v1/loans/${id}/schedule`),
        enabled: Boolean(id),
    });
}
export function usePayoffQuote(id, enabled) {
    return useQuery({
        queryKey: ["loans", "payoff-quote", id],
        queryFn: () => apiGet(`/api/v1/loans/${id}/payoff-quote`),
        enabled: Boolean(id) && enabled,
    });
}
/** Money movements keep one Idempotency-Key until they succeed, so a retry never pays twice. */
function useLoanPayment(path) {
    const invalidate = useInvalidateBanking();
    const client = useQueryClient();
    const once = useIdempotencyKey();
    return useMutation({
        mutationFn: ({ id, body }) => apiPost(path(id), body, once.key()),
        onSuccess: () => {
            once.renew();
            invalidate();
            // Repayments and servicing runs open and close collections cases (WF-0004).
            for (const key of ["workflow-executions", "workflow-tasks"])
                void client.invalidateQueries({ queryKey: [key] });
        },
    });
}
export const useRepayArrears = () => useLoanPayment((id) => `/api/v1/loans/${id}/repayments`);
export const usePayOffLoan = () => useLoanPayment((id) => `/api/v1/loans/${id}/payoff`);
export function useServicingRuns(params) {
    return useQuery({
        queryKey: ["loans", "servicing-runs", params],
        queryFn: () => apiGet(`/api/v1/loans/servicing-runs${query(params)}`),
        placeholderData: keepPreviousData,
    });
}
export function useRunServicing() {
    const invalidate = useInvalidateBanking();
    const client = useQueryClient();
    const once = useIdempotencyKey();
    return useMutation({
        mutationFn: (asOf) => apiPost("/api/v1/loans/servicing-runs", { as_of: asOf }, once.key()),
        onSuccess: () => {
            once.renew();
            invalidate();
            // Repayments and servicing runs open and close collections cases (WF-0004).
            for (const key of ["workflow-executions", "workflow-tasks"])
                void client.invalidateQueries({ queryKey: [key] });
        },
    });
}
