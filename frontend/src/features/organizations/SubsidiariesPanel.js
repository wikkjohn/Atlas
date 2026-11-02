import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { REGION_LABELS } from "@/services/format";
import { useGenerateSubsidiaries, useSubsidiaryBlueprint } from "@/services/enterprise";
import { useJob } from "@/services/jobs";
function JobProgress({ id }) {
    const job = useJob(id);
    const client = useQueryClient();
    const status = job.data?.status;
    useEffect(() => {
        if (status === "succeeded" || status === "failed") {
            void client.invalidateQueries({ queryKey: ["organizations"] });
            void client.invalidateQueries({ queryKey: ["countries"] });
        }
    }, [status, client]);
    if (!job.data)
        return null;
    const result = job.data.result;
    return (_jsxs("div", { role: "status", className: "space-y-1 text-xs text-slate-600", children: [_jsxs("p", { children: ["Job #", job.data.job_number, ": ", job.data.status, job.data.last_error && _jsxs("span", { className: "text-rose-700", children: [" \u2014 ", job.data.last_error] })] }), result && (_jsxs("p", { children: ["Launched ", result.launched.length, " of ", result.countries, " countries: ", result.organizations_created, " organizations,", " ", result.employees_hired, " staff."] })), result &&
                Object.entries(result.failed).map(([code, reason]) => (_jsxs("p", { className: "text-rose-700", children: [code, ": ", reason] }, code)))] }));
}
/** Country subsidiaries generated from the blueprint (Phase 27): coverage and generation. */
export function SubsidiariesPanel() {
    const { can } = useAuth();
    const blueprint = useSubsidiaryBlueprint();
    const generate = useGenerateSubsidiaries();
    const [region, setRegion] = useState("");
    const [codes, setCodes] = useState("");
    const [staff, setStaff] = useState(true);
    const data = blueprint.data;
    const onSubmit = (event) => {
        event.preventDefault();
        const countryCodes = codes
            .split(/[\s,]+/)
            .map((c) => c.trim().toUpperCase())
            .filter(Boolean);
        generate.mutate({
            ...(countryCodes.length ? { country_codes: countryCodes } : {}),
            ...(region && !countryCodes.length ? { region } : {}),
            staff,
        });
    };
    return (_jsxs(Panel, { title: "Country subsidiaries", subtitle: data
            ? `Blueprint v${data.version}: ${data.units_per_subsidiary} units and ${data.staff_per_subsidiary} synthetic staff per subsidiary. Launching a country makes it active and builds what its subsidiary is missing.`
            : undefined, children: [_jsx(ErrorMessage, { error: blueprint.error }), _jsxs("table", { "aria-label": "Subsidiary coverage", className: "min-w-full text-sm", children: [_jsx("thead", { className: "text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-2 py-1", children: "Region" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Countries" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Subsidiaries" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Generated" }), _jsx("th", { className: "px-2 py-1", children: "Without a subsidiary" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: data?.coverage.map((row) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 text-slate-900", children: REGION_LABELS[row.region] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: row.countries }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: row.subsidiaries }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: row.generated }), _jsx("td", { className: "px-2 py-1.5 font-mono text-[11px] text-slate-500", children: row.without_subsidiary.length === 0
                                        ? "—"
                                        : row.without_subsidiary.slice(0, 12).join(" ") + (row.without_subsidiary.length > 12 ? ` +${row.without_subsidiary.length - 12}` : "") })] }, row.region))) })] }), can("organizations:manage") && (_jsxs("form", { onSubmit: onSubmit, "aria-label": "Generate subsidiaries", className: "mt-4 flex flex-wrap items-center gap-2", children: [_jsx("input", { "aria-label": "Country codes", placeholder: "Country codes, e.g. KE GH (blank: all without one)", className: "w-72 rounded-md border border-slate-200 px-2 py-1 text-xs", value: codes, onChange: (e) => setCodes(e.target.value) }), _jsxs("select", { "aria-label": "Region", className: "rounded-md border border-slate-200 px-2 py-1 text-xs", value: region, disabled: codes.trim() !== "", onChange: (e) => setRegion(e.target.value), children: [_jsx("option", { value: "", children: "All regions" }), Object.keys(REGION_LABELS).map((r) => (_jsx("option", { value: r, children: REGION_LABELS[r] }, r)))] }), _jsxs("label", { className: "flex items-center gap-1 text-xs text-slate-600", children: [_jsx("input", { type: "checkbox", checked: staff, onChange: (e) => setStaff(e.target.checked) }), "Hire staff"] }), _jsx(Button, { size: "sm", type: "submit", disabled: generate.isPending, children: "Generate" })] })), _jsx(ErrorMessage, { error: generate.error }), generate.data && _jsx(JobProgress, { id: generate.data.id }, generate.data.id)] }));
}
