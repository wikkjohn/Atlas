import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query } from "@/services/api";
export const useFxRates = (on) => useQuery({
    queryKey: ["fx", "rates", on],
    queryFn: () => apiGet(`/api/v1/fx/rates${query({ on })}`),
});
export const useFxQuote = () => useMutation({
    mutationFn: (body) => apiPost("/api/v1/fx/quote", body),
});
export const useFxPositions = (asOf, enabled = true) => useQuery({
    queryKey: ["fx", "positions", asOf],
    queryFn: () => apiGet(`/api/v1/fx/positions${query({ as_of: asOf })}`),
    enabled,
});
export const useFxRevaluations = (enabled = true) => useQuery({
    queryKey: ["fx", "revaluations"],
    queryFn: () => apiGet(`/api/v1/fx/revaluations${query({ limit: 10 })}`),
    enabled,
});
export const useFxDeals = (enabled = true) => useQuery({
    queryKey: ["fx", "deals"],
    queryFn: () => apiGet(`/api/v1/fx/deals${query({ limit: 15 })}`),
    enabled,
});
export function useRevalue() {
    const client = useQueryClient();
    return useMutation({
        mutationFn: (asOf) => apiPost("/api/v1/fx/revaluations", { as_of: asOf }),
        onSuccess: () => client.invalidateQueries({ queryKey: ["fx"] }),
    });
}
