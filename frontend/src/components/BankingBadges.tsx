import { StatusPill, type Tone } from "@/components/StatusPill";
import { humanize } from "@/services/format";
import type { AccountStatus, KycStatus, RequestStatus, RiskRating } from "@/types/banking";

const KYC: Record<KycStatus, Tone> = {
  not_started: "neutral",
  pending: "warn",
  verified: "good",
  rejected: "bad",
};
const RISK: Record<RiskRating, Tone> = { unrated: "neutral", low: "good", medium: "warn", high: "bad" };
const ACCOUNT: Record<AccountStatus, Tone> = { open: "good", frozen: "warn", closed: "neutral" };
const REQUEST: Record<RequestStatus, Tone> = { pending: "warn", approved: "good", rejected: "bad" };

export const KycBadge = ({ status }: { status: KycStatus }) => (
  <StatusPill tone={KYC[status]} label={`KYC ${humanize(status).toLowerCase()}`} />
);
export const RiskBadge = ({ rating }: { rating: RiskRating }) => (
  <StatusPill tone={RISK[rating]} label={rating === "unrated" ? "Unrated" : `${humanize(rating)} risk`} />
);
export const AccountStatusBadge = ({ status }: { status: AccountStatus }) => (
  <StatusPill tone={ACCOUNT[status]} label={humanize(status)} />
);
export const RequestStatusBadge = ({ status }: { status: RequestStatus }) => (
  <StatusPill tone={REQUEST[status]} label={humanize(status)} />
);

export const ACCOUNT_TYPE_LABELS = {
  current: "Current",
  savings: "Savings",
  business_current: "Business current",
} as const;
