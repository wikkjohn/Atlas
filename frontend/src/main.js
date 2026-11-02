import { jsx as _jsx } from "react/jsx-runtime";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/app/App";
import "@/index.css";
const root = document.getElementById("root");
if (!root)
    throw new Error("Root element #root not found");
createRoot(root).render(_jsx(StrictMode, { children: _jsx(App, {}) }));
