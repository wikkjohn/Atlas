import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "@/app/AppRoutes";
import { AuthProvider } from "@/app/auth";
import { setAccessToken } from "@/services/api";

const SESSION_KEY = "atlas.session";

/**
 * Render the full app at `path`. With `signedIn` (the default) a stored session exists, so
 * the app validates it via GET /api/v1/auth/me — the test's mocked routes decide who that is.
 */
export function renderApp(path = "/", { signedIn = true } = {}) {
  sessionStorage.clear();
  setAccessToken(null);
  if (signedIn) {
    sessionStorage.setItem(
      SESSION_KEY,
      JSON.stringify({
        token: "test-token",
        expiresAt: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
      }),
    );
  }
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}
