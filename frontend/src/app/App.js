import { jsx as _jsx } from "react/jsx-runtime";
import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "@/app/AppRoutes";
import { AuthProvider } from "@/app/auth";
import { createQueryClient } from "@/services/queries";
export function App() {
    const [queryClient] = useState(createQueryClient);
    return (_jsx(QueryClientProvider, { client: queryClient, children: _jsx(AuthProvider, { children: _jsx(BrowserRouter, { children: _jsx(AppRoutes, {}) }) }) }));
}
