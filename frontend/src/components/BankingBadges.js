import { jsx as _jsx } from "react/jsx-runtime";
import { StatusPill } from "@/components/StatusPill";
import { humanize } from "@/services/format";
const KYC = {
    not_started: "neutral",
    pending: "warn",
    verified: "good",
    rejected: "bad",
};
const RISK = { unrated: "neutral", low: "good", medium: "warn", high: "bad" };
const ACCOUNT = { open: "good", frozen: "warn", closed: "neutral" };
const REQUEST = { pending: "warn", approved: "good", rejected: "bad" };
export const KycBadge = ({ status }) => (_jsx(StatusPill, { tone: KYC[status], label: `KYC ${humanize(status).toLowerCase()}` }));
export const RiskBadge = ({ rating }) => (_jsx(StatusPill, { tone: RISK[rating], label: rating === "unrated" ? "Unrated" : `${humanize(rating)} risk` }));
export const AccountStatusBadge = ({ status }) => (_jsx(StatusPill, { tone: ACCOUNT[status], label: humanize(status) }));
export const RequestStatusBadge = ({ status }) => (_jsx(StatusPill, { tone: REQUEST[status], label: humanize(status) }));
export const ACCOUNT_TYPE_LABELS = {
    current: "Current",
    savings: "Savings",
    business_current: "Business current",
};
