import { QueryClient, useQuery } from "@tanstack/react-query";

import { getHealth, getSystemInfo, getSystemStatus } from "@/services/api";

export const HEALTH_POLL_MS = 15_000;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 5_000 },
    },
  });
}

export const queryKeys = {
  health: ["system", "health"] as const,
  info: ["system", "info"] as const,
  status: ["system", "status"] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: getHealth,
    refetchInterval: HEALTH_POLL_MS,
  });
}

export function useSystemInfo() {
  return useQuery({ queryKey: queryKeys.info, queryFn: getSystemInfo });
}

export function useSystemStatus() {
  return useQuery({
    queryKey: queryKeys.status,
    queryFn: getSystemStatus,
    refetchInterval: HEALTH_POLL_MS,
  });
}
