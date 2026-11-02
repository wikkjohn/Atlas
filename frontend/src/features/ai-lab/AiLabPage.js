import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { FlaskConical, Play, Plus, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatTimestamp } from "@/features/dashboard/format";
import { useActions, useAdapters, useAiTool, useAiTools, useInvocations, useInvokeTool, useRegisterTool, useSetToolStatus, useStartSuite, useSuiteRuns, } from "@/services/aiTools";
import { humanize } from "@/services/format";
import { useScenarios, useSimulationRun } from "@/services/simulations";
import { useWorkflows } from "@/services/workflows";
import { MODE_LABELS } from "@/types/simulations";
const INVOCATION_TONE = {
    succeeded: "good",
    failed: "bad",
    timeout: "bad",
    invalid_input: "warn",
    invalid_output: "bad",
    blocked: "bad",
};
const RUN_TONE = {
    queued: "neutral",
    running: "warn",
    completed: "good",
    failed: "bad",
};
const ALL_MODES = ["baseline", "ai_assisted", "ai_automated"];
const INVOCATIONS_PAGE = 10;
const TOOL_ID = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const SEMVER = /^\d+\.\d+\.\d+$/;
/** A valid synthetic application for the KYC test console (fictional applicant). */
const SAMPLE_INPUT = {
    application: {
        applicant_name: "Mia Novak",
        date_of_birth: "1990-04-12",
        country_code: "DE",
        account_type: "current",
        documents: [
            {
                document_type: "national_id",
                document_number: "N12345678",
                name_on_document: "Mia Novak",
                date_of_birth: "1990-04-12",
                expiry_date: "2031-06-30",
            },
            { document_type: "proof_of_address", document_number: "A76543218", name_on_document: "Mia Novak" },
        ],
        politically_exposed: false,
        expected_monthly_deposits: 4000,
    },
    screening: { sanctions_hit: false },
    as_of: "2026-01-05",
};
/** A synthetic held payment for the payment screener's test console. */
const SAMPLE_PAYMENT = {
    payment: { amount: 450000, currency: "GBP", reference: "Gift card codes", channel: "online", high_value: false },
    signals: { sanctions_hit: false, new_payee: true, recent_payments_24h: 0, share_of_balance: 0.6 },
    as_of: "2026-01-06",
};
/** A referred synthetic loan application whose declared income is twice the estimate. */
const SAMPLE_LOAN = {
    application: {
        amount: 1500000,
        currency: "EUR",
        term_months: 48,
        purpose: "vehicle",
        employment_status: "employed",
        monthly_income: 900000,
        monthly_debt_payments: 30000,
    },
    bureau: { score: 742, recent_defaults: 0, open_credit_lines: 2 },
    affordability: { annual_rate_bps: 890, monthly_payment: 37254, debt_to_income: 0.0747, committee_required: false },
    income: { estimated_monthly_income: 450000, declared_to_estimate: 2.0 },
    as_of: "2026-01-07",
};
/** An overdraft request from a customer overdrawn most days: the assistant's blind spot (Phase 30). */
const SAMPLE_OVERDRAFT = {
    limit: 150000,
    profile: {
        currency: "USD",
        balance: -42000,
        overdraft_limit: 75000,
        max_overdraft: 250000,
        monthly_credits: 380000,
        months_with_credits: 3,
        days_overdrawn: 81,
    },
    as_of: "2026-04-07",
};
/** Card testing at home: tiny test purchases, then crypto — the fraud assistant's blind spot (Phase 32). */
const SAMPLE_CARD_FRAUD = {
    profile: {
        currency: "USD",
        home_country: "US",
        daily_limit: 150000,
        blocked: {
            auth_code: "AUTH-00000042",
            merchant_name: "Coin Exchange",
            merchant_category: "6051",
            merchant_country: "US",
            abroad: false,
            amount: 12000,
            fraud_score: 70,
            fraud_signals: ["high_risk_category", "velocity"],
        },
        purchases_90d: 17,
        median_amount: 5200,
        high_risk_purchases_90d: 0,
        country_first_seen_hours: null,
        attempts_last_hour: [110, 95, 180, 60, 150],
    },
};
/** Prime figures, but the term ends when the applicant is 94: the underwriting assistant's blind spot (Phase 34). */
const SAMPLE_MORTGAGE = {
    profile: {
        currency: "GBP",
        product_code: "home-75",
        loan_amount: 18000000,
        term_years: 35,
        ltv_bps: 6000,
        monthly_payment: 87000,
        declared_monthly_income: 520000,
        income_estimate: 540000,
        payment_to_income_bps: 1673,
        payment_to_estimate_bps: 1611,
        declared_to_estimate_bps: 9629,
        credit_score: 781,
        recent_defaults: 0,
        valuation_method: "surveyor",
        model_to_price_bps: 10200,
        age_at_term_end: 94,
    },
};
/** A second near miss a year after a waiver: the covenant assistant's blind spot (Phase 36). */
const SAMPLE_COVENANT = {
    profile: {
        currency: "GBP",
        facility_type: "revolving",
        dscr_centi: 117,
        dscr_threshold_centi: 125,
        leverage_centi: 280,
        leverage_threshold_centi: 350,
        ebitda_change_bps: -150,
        previous_ebitda_change_bps: -2100,
        consecutive_declines: 2,
        utilisation_bps: 4500,
        periods_tested: 3,
        previous_breaches: 1,
        previous_waivers: 1,
    },
};
/** The same late presentation the bank rejected before: the document check assistant's blind spot (Phase 38). */
const SAMPLE_DOCUMENT_CHECK = {
    profile: {
        currency: "GBP",
        kind: "letter_of_credit",
        discrepancy: "late_presentation",
        discrepancy_count: 1,
        draw_share_bps: 4000,
        days_to_expiry: 75,
        funding_cover_bps: 25000,
        earlier_presentations: 1,
        earlier_rejected: 1,
        earlier_same_discrepancy: 1,
    },
};
/** A dealer's double-keyed placement: the back-office check assistant's blind spot (Phase 40). */
const SAMPLE_BACK_OFFICE = {
    profile: {
        kind: "placement",
        currency: "USD",
        rate_bps: 530,
        reference_rate_bps: 525,
        rate_against_bank_bps: -5,
        tenor_days: 30,
        rating: "AA",
        limit_utilisation_bps: 4200,
        coverage_after_bps: 48000,
        same_day_duplicates: 1,
    },
};
/** A customer request from a payer with four recent recalls, three refused: the recall assistant's blind spot (Phase 42). */
const SAMPLE_RECALL = {
    profile: {
        reason_code: "CUST",
        currency: "GBP",
        amount: 250000,
        high_value: false,
        days_since_settlement: 2,
        window_days: 5,
        days_left: 3,
        duplicate_matches: 0,
        payee_history: 0,
        payer_recalls_90d: 4,
        payer_refused_90d: 3,
    },
};
const SAMPLE_SUITABILITY = {
    profile: {
        reasons: ["risk_above_profile"],
        security_code: "AGB-GLOBAL-EQ",
        asset_class: "fund",
        risk_level: 5,
        complex: false,
        risk_profile: 4,
        risk_gap: 1,
        objective: "balanced",
        knowledge: "informed",
        horizon_years: 12,
        loss_capacity: "high",
        amount: 600000,
        currency: "USD",
        share_after_pct: 18,
        cash_after_pct: 70,
        experienced: true,
        insisted_90d: 4,
        refused_90d: 1,
    },
};
const SAMPLE_ALERT = {
    profile: {
        rule: "large_cash",
        score: 80,
        currency: "GBP",
        amount: 2400000,
        amount_x_threshold_pct: 302,
        deposits: 4,
        customer_type: "business",
        customer_risk: "low",
        credits: 2400000,
        baseline_monthly_credits: 2300000,
        activity_vs_baseline_pct: 104,
        prior_alerts_365d: 3,
        prior_reports_filed: 0,
    },
};
const SAMPLE_RATING = {
    profile: {
        customer_type: "individual",
        kyc_risk: "medium",
        suggested_grade: 6,
        proposed_grade: 5,
        notches: -1,
        direction: "upgrade",
        worst_days_past_due: 0,
        frozen_facility: false,
        exposure_usd: 3200,
        overdraft_usd: 0,
        overdraft_use_pct: 0,
        monthly_inflow_usd: 2400,
        exposure_to_annual_inflow_pct: 11,
        limit_at_model_usd: 2000000,
        limit_at_proposed_usd: 2000000,
        rationale_chars: 42,
        prior_overrides_365d: 3,
        prior_overrides_rejected_365d: 3,
    },
};
const SAMPLE_JOURNAL = {
    profile: {
        currency: "USD",
        amount: 9000000,
        amount_usd: 90000,
        materiality_pct: 90,
        lines: 2,
        account_types: ["expense", "liability"],
        touches_equity: false,
        touches_income: false,
        touches_cash: false,
        effective_date: "2026-10-20",
        days_backdated: 0,
        in_closed_period: false,
        round_amount: false,
        description_chars: 58,
        duplicate_of: null,
        same_accounts_7d: 2,
        same_accounts_7d_usd: 172000,
    },
};
const SAMPLE_COMPLAINT = {
    profile: {
        topic: "fees",
        channel: "phone",
        currency: "USD",
        redress_amount: 750,
        redress_usd: 7,
        fees_90d: 1,
        fees_90d_amount: 750,
        duplicate_fee: false,
        redress_to_fees_pct: 100,
        account_age_days: 420,
        description_chars: 64,
        prior_complaints_365d: 4,
        prior_upheld_365d: 4,
        prior_redress_paid_365d_usd: 30,
    },
};
const SAMPLES = {
    rule_based_payment_screening: SAMPLE_PAYMENT,
    rule_based_credit_underwriting: SAMPLE_LOAN,
    rule_based_overdraft_affordability: SAMPLE_OVERDRAFT,
    rule_based_card_fraud_review: SAMPLE_CARD_FRAUD,
    rule_based_mortgage_underwriting: SAMPLE_MORTGAGE,
    rule_based_covenant_review: SAMPLE_COVENANT,
    rule_based_document_check: SAMPLE_DOCUMENT_CHECK,
    rule_based_back_office_check: SAMPLE_BACK_OFFICE,
    rule_based_recall_review: SAMPLE_RECALL,
    rule_based_suitability_review: SAMPLE_SUITABILITY,
    rule_based_alert_review: SAMPLE_ALERT,
    rule_based_rating_review: SAMPLE_RATING,
    rule_based_journal_review: SAMPLE_JOURNAL,
    rule_based_complaint_review: SAMPLE_COMPLAINT,
};
const CONSOLE_ACTIONS = [
    "analyze_application",
    "analyze_payment",
    "analyze_credit_application",
    "recommend_decision",
    "complete_low_risk_review",
];
// --- Registration ---------------------------------------------------------------------------
function RegisterToolDialog({ onClose, onRegistered }) {
    const adapters = useAdapters();
    const actions = useActions();
    const workflows = useWorkflows();
    const register = useRegisterTool();
    const [form, setForm] = useState({
        tool_id: "",
        tool_name: "",
        tool_version: "1.0.0",
        provider: "",
        description: "",
        adapter: "rule_based_kyc",
    });
    const [chosenActions, setChosenActions] = useState(["analyze_application", "recommend_decision"]);
    const [chosenWorkflows, setChosenWorkflows] = useState(["WF-0001"]);
    const [configuration, setConfiguration] = useState("{}");
    const [submitted, setSubmitted] = useState(false);
    const adapter = adapters.data?.find((a) => a.key === form.adapter);
    let parsedConfig = null;
    try {
        const value = JSON.parse(configuration);
        parsedConfig = value && typeof value === "object" && !Array.isArray(value) ? value : null;
    }
    catch {
        parsedConfig = null;
    }
    const errors = {
        tool_id: TOOL_ID.test(form.tool_id) ? null : "Lower-case letters, digits and single hyphens.",
        tool_name: form.tool_name.trim().length >= 3 ? null : "At least 3 characters.",
        tool_version: SEMVER.test(form.tool_version) ? null : "A semantic version such as 1.0.0.",
        provider: form.provider.trim().length >= 2 ? null : "Required.",
        actions: chosenActions.length > 0 ? null : "Grant at least one action.",
        configuration: parsedConfig ? null : "Must be a JSON object.",
    };
    const valid = Object.values(errors).every((e) => e === null);
    const show = (error) => (submitted ? error : null);
    const set = (key) => (value) => setForm({ ...form, [key]: value });
    const toggle = (list, value) => list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
    const submit = (event) => {
        event.preventDefault();
        setSubmitted(true);
        if (!valid || !parsedConfig)
            return;
        register.mutate({
            ...form,
            allowed_actions: chosenActions,
            compatible_workflows: chosenWorkflows,
            permissions: [],
            configuration: parsedConfig,
        }, { onSuccess: (tool) => onRegistered(tool.id) });
    };
    return (_jsxs(Modal, { title: "Register an AI tool", onClose: onClose, children: [_jsxs("form", { id: "register-tool", "aria-label": "Register an AI tool", onSubmit: submit, className: "space-y-3", children: [_jsxs("div", { className: "grid gap-3 sm:grid-cols-2", children: [_jsx(Field, { label: "Tool ID", error: show(errors.tool_id), children: (p) => _jsx("input", { ...p, className: inputClass, value: form.tool_id, onChange: (e) => set("tool_id")(e.target.value) }) }), _jsx(Field, { label: "Version", error: show(errors.tool_version), children: (p) => (_jsx("input", { ...p, className: inputClass, value: form.tool_version, onChange: (e) => set("tool_version")(e.target.value) })) })] }), _jsx(Field, { label: "Name", error: show(errors.tool_name), children: (p) => _jsx("input", { ...p, className: inputClass, value: form.tool_name, onChange: (e) => set("tool_name")(e.target.value) }) }), _jsx(Field, { label: "Provider", error: show(errors.provider), children: (p) => _jsx("input", { ...p, className: inputClass, value: form.provider, onChange: (e) => set("provider")(e.target.value) }) }), _jsx(Field, { label: "Description", children: (p) => (_jsx("textarea", { ...p, rows: 2, className: inputClass, value: form.description, onChange: (e) => set("description")(e.target.value) })) }), _jsx(Field, { label: "Implementation (adapter)", hint: adapter?.description, children: (p) => (_jsx("select", { ...p, className: inputClass, value: form.adapter, onChange: (e) => set("adapter")(e.target.value), children: (adapters.data ?? []).map((a) => (_jsx("option", { value: a.key, children: a.name }, a.key))) })) }), _jsxs("fieldset", { children: [_jsx("legend", { className: "text-xs font-medium text-slate-700", children: "Allowed actions" }), _jsx("div", { className: "mt-1 space-y-1", children: (actions.data ?? []).map((a) => {
                                    const supported = a.grantable && (adapter?.supported_actions.includes(a.action) ?? false);
                                    return (_jsxs("label", { className: `flex items-start gap-2 text-xs ${supported ? "text-slate-700" : "text-slate-400"}`, children: [_jsx("input", { type: "checkbox", disabled: !supported, checked: chosenActions.includes(a.action), onChange: () => setChosenActions(toggle(chosenActions, a.action)) }), _jsxs("span", { children: [_jsx("span", { className: "font-mono", children: a.action }), !a.grantable && " (never grantable)", " \u2014 ", a.description] })] }, a.action));
                                }) }), show(errors.actions) && _jsx("p", { className: "mt-1 text-xs text-rose-600", children: errors.actions })] }), _jsxs("fieldset", { children: [_jsx("legend", { className: "text-xs font-medium text-slate-700", children: "Compatible workflows" }), _jsx("div", { className: "mt-1 flex flex-wrap gap-3", children: (workflows.data ?? []).map((w) => (_jsxs("label", { className: "flex items-center gap-2 text-xs text-slate-700", children: [_jsx("input", { type: "checkbox", checked: chosenWorkflows.includes(w.workflow_id), onChange: () => setChosenWorkflows(toggle(chosenWorkflows, w.workflow_id)) }), w.workflow_id, " ", w.name] }, w.workflow_id))) })] }), _jsx(Field, { label: "Configuration (JSON)", hint: "Validated by the adapter; omitted values use its defaults.", error: show(errors.configuration), children: (p) => (_jsx("textarea", { ...p, rows: 3, className: `${inputClass} font-mono text-xs`, value: configuration, onChange: (e) => setConfiguration(e.target.value) })) })] }), _jsx(ErrorMessage, { error: register.error, className: "mt-3" }), _jsxs("div", { className: "mt-4 flex justify-end gap-2", children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: "register-tool", disabled: register.isPending, children: "Register tool" })] })] }));
}
// --- Test console -----------------------------------------------------------------------------
function TestConsole({ tool }) {
    const invoke = useInvokeTool(tool.id);
    const [action, setAction] = useState(tool.allowed_actions[0] ?? "analyze_application");
    const [input, setInput] = useState(JSON.stringify(SAMPLES[tool.adapter] ?? SAMPLE_INPUT, null, 2));
    let parsed = null;
    try {
        parsed = JSON.parse(input);
    }
    catch {
        parsed = null;
    }
    const result = invoke.data;
    const output = result?.output;
    return (_jsxs("form", { "aria-label": "Test console", className: "space-y-3", onSubmit: (e) => {
            e.preventDefault();
            if (parsed)
                invoke.mutate({ action, input: parsed });
        }, children: [_jsx(Field, { label: "Action", hint: "Actions the tool was not granted are refused and recorded.", children: (p) => (_jsx("select", { ...p, className: inputClass, value: action, onChange: (e) => setAction(e.target.value), children: CONSOLE_ACTIONS.map((a) => (_jsxs("option", { value: a, children: [a, tool.allowed_actions.includes(a) ? "" : " (not granted)"] }, a))) })) }), _jsx(Field, { label: "Request (synthetic data)", error: parsed ? null : "Not valid JSON.", children: (p) => (_jsx("textarea", { ...p, rows: 8, className: `${inputClass} font-mono text-xs`, value: input, onChange: (e) => setInput(e.target.value) })) }), _jsxs(Button, { type: "submit", disabled: invoke.isPending || !parsed, children: [_jsx(Play, { "aria-hidden": true, className: "h-4 w-4" }), " Invoke"] }), _jsx(ErrorMessage, { error: invoke.error }), result && (_jsxs("div", { role: "status", className: "rounded-lg border border-slate-200 p-3 text-sm", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx(StatusPill, { tone: INVOCATION_TONE[result.status], label: humanize(result.status) }), _jsxs("span", { className: "text-xs text-slate-500", children: [result.duration_ms, " ms"] })] }), output?.recommendation && (_jsxs("p", { className: "mt-2", children: [_jsxs("span", { className: "font-medium", children: ["Recommendation: ", humanize(output.recommendation)] }), " \u00B7", " ", humanize(output.risk_classification ?? ""), " risk"] })), output?.explanation && _jsx("p", { className: "mt-1 text-xs text-slate-600", children: output.explanation }), result.error && _jsx("pre", { className: "mt-2 overflow-x-auto text-xs text-rose-700", children: JSON.stringify(result.error, null, 2) })] }))] }));
}
// --- Experiments ------------------------------------------------------------------------------
function SuiteResults({ batchId }) {
    const suite = useSuiteRuns(batchId);
    const runs = [...(suite.data?.items ?? [])].sort((a, b) => a.run_number - b.run_number);
    return (_jsxs("div", { className: "space-y-2", children: [_jsx(ErrorMessage, { error: suite.error }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200", children: _jsxs("table", { "aria-label": "Experiment runs", className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-2", children: "Configuration" }), _jsx("th", { className: "px-3 py-2", children: "Status" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Accuracy" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Manual reviews" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Review hours" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Policy approvals" }), _jsx("th", { className: "px-3 py-2 text-right", children: "AI failures" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: runs.map((run) => (_jsx(SuiteRow, { run: run }, run.id))) })] }) }), _jsx("p", { className: "text-[11px] text-slate-500", children: "Simulated measurements on synthetic data. AI-assisted review times and accuracy rest on the scenario's stated assumptions; costs and the formal comparison come with Benchmarking (Phase 7)." })] }));
}
function SuiteRow({ run }) {
    const detail = useSimulationRun(run.id);
    const res = detail.data?.results;
    const status = detail.data?.status ?? run.status;
    return (_jsxs("tr", { children: [_jsxs("td", { className: "px-3 py-2", children: [_jsx(Link, { className: "font-medium text-navy-700 hover:underline", to: `/simulations?run=${run.id}`, children: MODE_LABELS[run.mode] }), _jsxs("div", { className: "text-[11px] text-slate-500", children: ["Run #", run.run_number] })] }), _jsxs("td", { className: "px-3 py-2", children: [_jsx(StatusPill, { tone: RUN_TONE[status], label: humanize(status) }), status === "running" && _jsxs("span", { className: "ml-1 text-xs text-slate-500", children: [detail.data?.percent_complete, "%"] })] }), _jsx("td", { className: "px-3 py-2 text-right", children: res?.ground_truth.accuracy != null ? `${(res.ground_truth.accuracy * 100).toFixed(1)}%` : "—" }), _jsx("td", { className: "px-3 py-2 text-right", children: res?.manual_reviews ?? "—" }), _jsx("td", { className: "px-3 py-2 text-right", children: res?.review_labor_hours != null ? res.review_labor_hours.toFixed(1) : "—" }), _jsx("td", { className: "px-3 py-2 text-right", children: res?.ai?.automated_approvals ?? "—" }), _jsx("td", { className: "px-3 py-2 text-right", children: res?.ai ? res.ai.failed_invocations : "—" })] }));
}
function ExperimentForm({ tool, onStarted }) {
    const scenarios = useScenarios();
    const start = useStartSuite();
    const candidates = (scenarios.data ?? []).filter((s) => s.modes.length > 1 && tool.compatible_workflows.includes(s.workflow_id));
    const [scenarioKey, setScenarioKey] = useState("");
    const scenario = candidates.find((s) => `${s.scenario_id}@${s.version}` === scenarioKey) ?? candidates[0];
    const [modes, setModes] = useState(ALL_MODES);
    const [applications, setApplications] = useState("100");
    const [employees, setEmployees] = useState("25");
    const [seed, setSeed] = useState("42");
    const seedValue = Number(seed);
    const sizeOk = Number(applications) >= 1 && Number(applications) <= 10000 && Number(employees) >= 3 && Number(employees) <= 500;
    const valid = Boolean(scenario) && modes.length > 0 && Number.isInteger(seedValue) && seedValue >= 0 && sizeOk && tool.status === "active";
    if (candidates.length === 0) {
        return _jsx("p", { className: "text-sm text-slate-500", children: "No scenario with AI modes uses a workflow this tool is compatible with." });
    }
    return (_jsxs("form", { "aria-label": "Configure an experiment", className: "space-y-3", onSubmit: (e) => {
            e.preventDefault();
            if (!valid || !scenario)
                return;
            start.mutate({
                scenario_id: scenario.scenario_id,
                scenario_version: scenario.version,
                profile: "custom",
                applications: Number(applications),
                employees: Number(employees),
                seed: seedValue,
                modes,
                tool_id: tool.tool_id,
                tool_version: tool.tool_version,
            }, { onSuccess: (runs) => runs[0]?.batch_id && onStarted(runs[0].batch_id) });
        }, children: [_jsx(Field, { label: "Workflow and scenario", children: (p) => (_jsx("select", { ...p, className: inputClass, value: scenario ? `${scenario.scenario_id}@${scenario.version}` : "", onChange: (e) => setScenarioKey(e.target.value), children: candidates.map((s) => (_jsxs("option", { value: `${s.scenario_id}@${s.version}`, children: [s.workflow_id, " \u2014 ", s.name, " (v", s.version, ")"] }, `${s.scenario_id}@${s.version}`))) })) }), _jsxs("fieldset", { children: [_jsx("legend", { className: "text-xs font-medium text-slate-700", children: "Configurations" }), _jsx("div", { className: "mt-1 flex flex-wrap gap-3", children: ALL_MODES.map((m) => (_jsxs("label", { className: "flex items-center gap-2 text-xs text-slate-700", children: [_jsx("input", { type: "checkbox", checked: modes.includes(m), onChange: () => setModes(modes.includes(m) ? modes.filter((x) => x !== m) : ALL_MODES.filter((x) => x === m || modes.includes(x))) }), MODE_LABELS[m]] }, m))) })] }), _jsxs("div", { className: "grid grid-cols-3 gap-3", children: [_jsx(Field, { label: "Cases", hint: "1 \u2013 10,000", children: (p) => _jsx("input", { ...p, type: "number", className: inputClass, value: applications, onChange: (e) => setApplications(e.target.value) }) }), _jsx(Field, { label: "Staff", hint: "3 \u2013 500", children: (p) => _jsx("input", { ...p, type: "number", className: inputClass, value: employees, onChange: (e) => setEmployees(e.target.value) }) }), _jsx(Field, { label: "Seed", children: (p) => _jsx("input", { ...p, inputMode: "numeric", className: inputClass, value: seed, onChange: (e) => setSeed(e.target.value) }) })] }), _jsxs(Button, { type: "submit", disabled: !valid || start.isPending, children: [_jsx(FlaskConical, { "aria-hidden": true, className: "h-4 w-4" }), " Start test runs"] }), _jsx(ErrorMessage, { error: start.error })] }));
}
// --- Tool detail ------------------------------------------------------------------------------
function ToolDetail({ id }) {
    const { can } = useAuth();
    const tool = useAiTool(id);
    const setStatus = useSetToolStatus();
    const [offset, setOffset] = useState(0);
    const invocations = useInvocations(id, offset, INVOCATIONS_PAGE);
    const [params, setParams] = useSearchParams();
    const suite = params.get("suite");
    const t = tool.data;
    if (tool.error)
        return _jsx(ErrorMessage, { error: tool.error });
    if (!t)
        return _jsx("p", { className: "text-sm text-slate-500", children: "Loading\u2026" });
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsx("h2", { className: "text-lg font-semibold text-slate-900", children: t.tool_name }), _jsxs("span", { className: "text-xs text-slate-500", children: ["v", t.tool_version] }), _jsx(StatusPill, { tone: t.status === "active" ? "good" : "neutral", label: humanize(t.status) })] }), _jsx("p", { className: "mt-1 text-sm text-slate-600", children: t.description }), _jsxs("p", { className: "mt-1 text-xs text-slate-500", children: [t.provider, " \u00B7 adapter ", _jsx("span", { className: "font-mono", children: t.adapter }), " \u00B7 ", t.invocations, " invocations, ", t.failures, " ", "not successful"] })] }), can("ai_tools:manage") && (_jsx(Button, { variant: "secondary", size: "sm", disabled: setStatus.isPending, onClick: () => setStatus.mutate({ id: t.id, status: t.status === "active" ? "disabled" : "active" }), children: t.status === "active" ? "Disable" : "Enable" }))] }), _jsx(ErrorMessage, { error: setStatus.error }), _jsxs("section", { "aria-label": "Capabilities", className: "grid gap-3 text-sm sm:grid-cols-2", children: [_jsxs("div", { className: "rounded-lg border border-slate-200 p-3", children: [_jsx("h3", { className: "mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "Allowed actions" }), _jsx("ul", { className: "space-y-0.5 font-mono text-xs", children: t.allowed_actions.map((a) => (_jsx("li", { children: a }, a))) }), _jsxs("p", { className: "mt-2 flex items-start gap-1 text-[11px] text-slate-500", children: [_jsx(ShieldAlert, { "aria-hidden": true, className: "mt-0.5 h-3 w-3 shrink-0" }), "Advisory only: the tool cannot approve accounts. The workflow policy engine and authorized people decide."] })] }), _jsxs("div", { className: "rounded-lg border border-slate-200 p-3", children: [_jsx("h3", { className: "mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "Compatible workflows" }), _jsx("p", { className: "text-xs", children: t.compatible_workflows.join(", ") || "None" }), _jsx("h3", { className: "mt-2 mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "Configuration" }), _jsx("pre", { className: "overflow-x-auto text-[11px] text-slate-600", children: JSON.stringify(t.configuration, null, 2) })] }), _jsxs("details", { className: "rounded-lg border border-slate-200 p-3 sm:col-span-2", children: [_jsx("summary", { className: "cursor-pointer text-xs font-semibold text-slate-700", children: "Input and output schemas" }), _jsxs("div", { className: "mt-2 grid gap-2 sm:grid-cols-2", children: [_jsx("pre", { className: "max-h-64 overflow-auto text-[11px] text-slate-600", children: JSON.stringify(t.input_schema, null, 2) }), _jsx("pre", { className: "max-h-64 overflow-auto text-[11px] text-slate-600", children: JSON.stringify(t.output_schema, null, 2) })] })] })] }), can("simulations:run") && (_jsxs("section", { "aria-label": "Experiment", className: "space-y-3", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Run an experiment" }), _jsx("p", { className: "text-xs text-slate-500", children: "Runs the chosen configurations one after another on the same seeded applications and staff. A: conventional rules and human review. B: the tool prepares summaries; people still decide. C: the policy engine may approve low-risk cases the tool recommends; everything else stays with people." }), _jsx(ExperimentForm, { tool: t, onStarted: (batch) => setParams({ tool: t.id, suite: batch }) })] })), suite && _jsx(SuiteResults, { batchId: suite }), can("ai_tools:invoke") && (_jsxs("section", { "aria-label": "Try the tool", className: "space-y-2", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Test console" }), _jsx(TestConsole, { tool: t })] })), _jsxs("section", { "aria-label": "Recorded invocations", children: [_jsx("h3", { className: "mb-2 text-sm font-semibold text-slate-900", children: "Recorded invocations" }), _jsx(ErrorMessage, { error: invocations.error }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200", children: _jsxs("table", { "aria-label": "Invocations", className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-2", children: "When" }), _jsx("th", { className: "px-3 py-2", children: "Action" }), _jsx("th", { className: "px-3 py-2", children: "Status" }), _jsx("th", { className: "px-3 py-2", children: "Result" }), _jsx("th", { className: "px-3 py-2", children: "Source" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [(invocations.data?.items ?? []).map((i) => (_jsxs("tr", { children: [_jsx("td", { className: "px-3 py-2 text-xs", children: formatTimestamp(i.created_at) }), _jsx("td", { className: "px-3 py-2 font-mono text-xs", children: i.action }), _jsx("td", { className: "px-3 py-2", children: _jsx(StatusPill, { tone: INVOCATION_TONE[i.status], label: humanize(i.status) }) }), _jsx("td", { className: "px-3 py-2 text-xs", children: typeof i.output?.recommendation === "string"
                                                        ? humanize(i.output.recommendation)
                                                        : typeof i.error?.message === "string"
                                                            ? i.error.message
                                                            : "—" }), _jsx("td", { className: "px-3 py-2 text-xs text-slate-500", children: i.simulation_run_id ? "Simulation" : i.execution_id ? "Workflow" : "Test console" })] }, i.id))), invocations.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 5, className: "px-3 py-6 text-center text-sm text-slate-500", children: "No invocations yet." }) }))] })] }) }), invocations.data && (_jsx(Pagination, { total: invocations.data.total, limit: INVOCATIONS_PAGE, offset: offset, onChange: setOffset }))] })] }));
}
// --- Page ------------------------------------------------------------------------------------
export function AiLabPage() {
    const { can } = useAuth();
    const tools = useAiTools();
    const [params, setParams] = useSearchParams();
    const [registering, setRegistering] = useState(false);
    const selected = params.get("tool") ?? tools.data?.items[0]?.id ?? null;
    return (_jsxs("div", { children: [_jsx(PageHeader, { title: "AI Innovation Lab", description: "Register AI tools behind one provider-independent contract, try them, and test them inside banking workflows against a baseline.", actions: _jsxs(_Fragment, { children: [_jsx(SyntheticDataBadge, {}), can("ai_tools:manage") && (_jsxs(Button, { onClick: () => setRegistering(true), children: [_jsx(Plus, { "aria-hidden": true, className: "h-4 w-4" }), " Register a tool"] }))] }) }), _jsxs("div", { className: "grid gap-6 lg:grid-cols-[18rem_1fr]", children: [_jsxs(Panel, { title: "Tool registry", children: [_jsx(ErrorMessage, { error: tools.error }), tools.data?.items.length === 0 && _jsx("p", { className: "text-sm text-slate-500", children: "No tools are registered yet." }), _jsx("ul", { "aria-label": "AI tools", className: "divide-y divide-slate-100", children: (tools.data?.items ?? []).map((tool) => (_jsx("li", { children: _jsxs("button", { type: "button", onClick: () => setParams({ tool: tool.id }), "aria-current": tool.id === selected ? "true" : undefined, className: `w-full px-2 py-2 text-left text-sm hover:bg-slate-50 ${tool.id === selected ? "bg-slate-50" : ""}`, children: [_jsxs("div", { className: "flex items-center justify-between gap-2", children: [_jsx("span", { className: "font-medium text-slate-900", children: tool.tool_name }), _jsx(StatusPill, { tone: tool.status === "active" ? "good" : "neutral", label: humanize(tool.status), compact: true })] }), _jsxs("div", { className: "text-xs text-slate-500", children: [tool.tool_id, " ", tool.tool_version, " \u00B7 ", tool.invocations, " calls"] })] }) }, tool.id))) })] }), _jsx(Panel, { title: "Tool details", children: selected ? _jsx(ToolDetail, { id: selected }, selected) : _jsx("p", { className: "text-sm text-slate-500", children: "Register a tool to begin." }) })] }), registering && (_jsx(RegisterToolDialog, { onClose: () => setRegistering(false), onRegistered: (id) => {
                    setRegistering(false);
                    setParams({ tool: id });
                } }))] }));
}
