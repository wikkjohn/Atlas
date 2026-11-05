/** Phase 84: sessions, the second factor, single sign-on and scopes. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDelete, apiGet, apiPost, apiPublicPost, apiPut } from "@/services/api";
import type { AuthSessionInfo, UserScope } from "@/types/enterprise";

export interface SsoProvider {
  id: string;
  name: string;
  simulated: boolean;
}

export interface SsoStart {
  provider: string;
  state: string;
  nonce: string;
  expires_at: string;
}

export function useMySessions() {
  return useQuery({
    queryKey: ["auth", "sessions"],
    queryFn: () => apiGet<AuthSessionInfo[]>("/api/v1/auth/sessions"),
  });
}

export function useEndSession() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/v1/auth/sessions/${id}`),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["auth", "sessions"] }),
  });
}

export function useEndOtherSessions() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<{ revoked: number }>("/api/v1/auth/sessions/revoke-others", {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["auth", "sessions"] }),
  });
}

export function useStartEnrolment() {
  return useMutation({
    mutationFn: () =>
      apiPost<{ secret: string; provisioning_uri: string }>("/api/v1/auth/mfa/enrol", {}),
  });
}

export function useConfirmEnrolment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (code: string) =>
      apiPost<{ recovery_codes: string[] }>("/api/v1/auth/mfa/confirm", { code }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["auth", "sessions"] }),
  });
}

export function useRegenerateRecoveryCodes() {
  return useMutation({
    mutationFn: (code: string) =>
      apiPost<{ recovery_codes: string[] }>("/api/v1/auth/mfa/recovery-codes", { code }),
  });
}

export function useRemoveMfa() {
  return useMutation({
    mutationFn: (code: string) => apiPost<null>("/api/v1/auth/mfa/remove", { code }),
  });
}

export function useSsoProviders() {
  return useQuery({
    queryKey: ["auth", "sso-providers"],
    queryFn: () => apiGet<SsoProvider[]>("/api/v1/auth/sso/providers"),
    staleTime: Infinity,
  });
}

export const startSso = (provider: string) =>
  apiPublicPost<SsoStart>(`/api/v1/auth/sso/${provider}/start`);

/** The simulated directory's sign-in: returns its signed ID token. */
export const directorySignIn = (
  provider: string,
  body: { nonce: string; username: string; password: string; otp?: string | null },
) => apiPublicPost<{ id_token: string }>(`/api/v1/simulated-directory/${provider}/sign-in`, body);

// --- Administration ---------------------------------------------------------------------

export function useUserSessions(userId: string | null) {
  return useQuery({
    queryKey: ["users", userId, "sessions"],
    queryFn: () => apiGet<AuthSessionInfo[]>(`/api/v1/users/${userId}/sessions`),
    enabled: Boolean(userId),
  });
}

export function useRevokeUserSessions() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      apiPost<{ revoked: number }>(`/api/v1/users/${userId}/sessions/revoke`, {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useResetMfa() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => apiPost<null>(`/api/v1/users/${userId}/mfa/reset`, {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useSetScopes() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, ...body }: { userId: string; countries: string[]; departments: string[] }) =>
      apiPut<UserScope>(`/api/v1/users/${userId}/scopes`, body),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["users"] }),
  });
}
