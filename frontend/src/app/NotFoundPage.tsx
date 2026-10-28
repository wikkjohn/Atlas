import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <p className="text-sm font-semibold text-gold-500">404</p>
      <h1 className="mt-2 text-xl font-semibold text-slate-900">Page not found</h1>
      <p className="mt-2 text-sm text-slate-500">
        This screen does not exist yet. Modules are added phase by phase.
      </p>
      <Link
        to="/"
        className="mt-6 inline-block rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white hover:bg-navy-800"
      >
        Back to overview
      </Link>
    </div>
  );
}
