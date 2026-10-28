import { ApiError, BackendUnreachableError } from "@/services/api";

/** Renders an API failure with its business-rule message and correlation ID. */
export function ErrorMessage({ error, className = "" }: { error: unknown; className?: string }) {
  if (!error) return null;
  let message = "Something went wrong.";
  let correlationId: string | null = null;
  let fieldErrors: string[] = [];
  if (error instanceof ApiError) {
    message =
      error.status === 403
        ? `Access denied: ${error.message}`
        : error.message;
    correlationId = error.correlationId;
    if (error.code === "validation_error" && Array.isArray(error.details)) {
      fieldErrors = (error.details as { location: string[]; message: string }[]).map(
        (d) => `${d.location.slice(1).join(".")}: ${d.message}`,
      );
    }
  } else if (error instanceof BackendUnreachableError) {
    message = "The ATLAS API could not be reached. Check that the backend is running.";
  } else if (error instanceof Error) {
    message = error.message;
  }
  return (
    <div
      role="alert"
      className={`rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 ${className}`}
    >
      <p>{message}</p>
      {fieldErrors.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-xs">
          {fieldErrors.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}
      {correlationId && (
        <p className="mt-1 font-mono text-[11px] text-rose-600">Reference: {correlationId}</p>
      )}
    </div>
  );
}
