import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query } from "@/services/api";
const BASE = "/api/v1/collections";
function useInvalidate() {
    const client = useQueryClient();
    return () => {
        void client.invalidateQueries({ queryKey: ["collections"] });
        void client.invalidateQueries({ queryKey: ["loans"] });
    };
}
export const useCollectionsSummary = () => useQuery({ queryKey: ["collections", "summary"], queryFn: () => apiGet(`${BASE}/summary/counts`) });
export const useArrears = () => useQuery({ queryKey: ["collections", "arrears"], queryFn: () => apiGet(`${BASE}/arrears`) });
export const usePlans = () => useQuery({ queryKey: ["collections", "plans"], queryFn: () => apiGet(`${BASE}/plans${query({ limit: 25 })}`) });
export const useWrittenOff = () => useQuery({ queryKey: ["collections", "written-off"], queryFn: () => apiGet(`${BASE}/written-off`) });
export const useRecoveries = () => useQuery({ queryKey: ["collections", "recoveries"], queryFn: () => apiGet(`${BASE}/recoveries${query({ limit: 25 })}`) });
export function useProposePlan() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost(`${BASE}/plans`, body),
        onSuccess: invalidate,
    });
}
export function useDecidePlan() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, approve }) => apiPost(`${BASE}/plans/${id}/${approve ? "approve" : "reject"}`, approve ? {} : { note: "Rejected on review" }),
        onSuccess: invalidate,
    });
}
export function useCollect() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: () => apiPost(`${BASE}/plans/collect`, {}),
        onSuccess: invalidate,
    });
}
export function useRecordRecovery() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost(`${BASE}/recoveries`, body),
        onSuccess: invalidate,
    });
}
export function useDecideRecovery() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, approve }) => apiPost(`${BASE}/recoveries/${id}/${approve ? "approve" : "reject"}`, approve ? {} : { note: "Rejected on review" }),
        onSuccess: invalidate,
    });
}
