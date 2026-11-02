import { useRef } from "react";
// Empty by default: the browser calls the same origin and the Vite dev server (or a
// reverse proxy in other environments) forwards /api to the backend.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
/** The backend answered, but with an error status. */
export class ApiError extends Error {
    status;
    code;
    correlationId;
    details;
    constructor(status, body) {
        super(body?.error?.message ?? `Request failed with HTTP ${status}`);
        this.name = "ApiError";
        this.status = status;
        this.code = body?.error?.code ?? "http_error";
        this.correlationId = body?.error?.correlation_id ?? null;
        this.details = body?.error?.details;
    }
}
/** The backend could not be reached at all (server down, proxy error, network failure). */
export class BackendUnreachableError extends Error {
    constructor(cause) {
        super("The ATLAS API could not be reached.", { cause });
        this.name = "BackendUnreachableError";
    }
}
// --- Session token -------------------------------------------------------------------
let accessToken = null;
let onUnauthorized = null;
export function setAccessToken(token) {
    accessToken = token;
}
/** Called when an authenticated request is rejected with 401 (expired or revoked token). */
export function setUnauthorizedHandler(handler) {
    onUnauthorized = handler;
}
async function request(method, path, options = {}) {
    const headers = { Accept: "application/json" };
    if (options.body !== undefined)
        headers["Content-Type"] = "application/json";
    if (accessToken && !options.anonymous)
        headers.Authorization = `Bearer ${accessToken}`;
    if (options.idempotencyKey)
        headers["Idempotency-Key"] = options.idempotencyKey;
    try {
        return await fetch(`${API_BASE_URL}${path}`, {
            method,
            headers,
            body: options.body === undefined ? undefined : JSON.stringify(options.body),
        });
    }
    catch (cause) {
        throw new BackendUnreachableError(cause);
    }
}
async function readJson(response) {
    try {
        return await response.json();
    }
    catch {
        return null;
    }
}
function isApiErrorBody(value) {
    return typeof value === "object" && value !== null && "error" in value;
}
async function send(method, path, options = {}) {
    const response = await request(method, path, options);
    const body = await readJson(response);
    if (!response.ok) {
        // The Vite proxy answers 502/503/504 with no JSON body when the backend is down.
        if (!isApiErrorBody(body) && [502, 503, 504].includes(response.status)) {
            throw new BackendUnreachableError(new Error(`HTTP ${response.status}`));
        }
        if (response.status === 401 && !options.anonymous && accessToken)
            onUnauthorized?.();
        throw new ApiError(response.status, isApiErrorBody(body) ? body : null);
    }
    return body;
}
export const apiGet = (path) => send("GET", path);
/** POSTs carry an Idempotency-Key so a retried submission never creates a duplicate. */
export const apiPost = (path, body, idempotencyKey = newIdempotencyKey()) => send("POST", path, { body, idempotencyKey });
export const apiPatch = (path, body) => send("PATCH", path, { body });
export const apiPut = (path, body) => send("PUT", path, { body });
/** Fetch a file (e.g. a report) with the caller's credentials. */
export async function apiDownload(path) {
    const response = await request("GET", path);
    if (!response.ok) {
        const body = await readJson(response);
        if (response.status === 401 && accessToken)
            onUnauthorized?.();
        throw new ApiError(response.status, isApiErrorBody(body) ? body : null);
    }
    return response.blob();
}
export const apiLogin = (body) => send("POST", "/api/v1/auth/login", { body, anonymous: true });
export function newIdempotencyKey() {
    return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
/** One Idempotency-Key per intended action: a retry after a failure (or a double click)
 * reuses it, so the server replays instead of acting twice; `renew` after success. */
export function useIdempotencyKey() {
    const ref = useRef(null);
    return {
        key: () => (ref.current ??= newIdempotencyKey()),
        renew: () => {
            ref.current = null;
        },
    };
}
/** Build a query string, skipping empty values. */
export function query(params) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null && value !== "")
            search.set(key, String(value));
    }
    const text = search.toString();
    return text ? `?${text}` : "";
}
// --- Platform endpoints (public) ---------------------------------------------------------
/** Health returns 503 *with a health report* when the database is down; that is data. */
export async function getHealth() {
    const response = await request("GET", "/api/health");
    const body = await readJson(response);
    if (body && typeof body === "object" && "components" in body) {
        return body;
    }
    if ([502, 503, 504].includes(response.status) || body === null) {
        throw new BackendUnreachableError(new Error(`HTTP ${response.status}`));
    }
    throw new ApiError(response.status, isApiErrorBody(body) ? body : null);
}
export const getSystemInfo = () => apiGet("/api/system/info");
export const getSystemStatus = () => apiGet("/api/system/status");
