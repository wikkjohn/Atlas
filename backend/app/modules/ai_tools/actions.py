"""What an AI tool may be permitted to do.

Tools are advisory. The grantable actions produce analysis and recommendations, or complete
a low-risk review task whose effect the workflow policy engine still decides. Actions that
would change banking records on a tool's own authority are never grantable: a tool asking
for one cannot be registered.
"""

GRANTABLE_ACTIONS: dict[str, str] = {
    "analyze_application": "Analyse a synthetic application and its documents (read-only).",
    "analyze_payment": "Analyse a synthetic payment and its screening signals (read-only).",
    "recommend_decision": "Recommend approve, reject or escalate (advisory only).",
    "complete_low_risk_review": "Complete a designated low-risk review task; the workflow "
    "policy engine decides whether the case may proceed without a person.",
}

FORBIDDEN_ACTIONS: dict[str, str] = {
    "approve_account": "Account approval belongs to authorized people and the policy engine.",
    "open_account": "Accounts are opened only by an approved request.",
    "reject_application": "Final decisions belong to the workflow and authorized people.",
    "change_kyc_status": "KYC decisions require the customers:review permission.",
    "post_ledger_entry": "Ledger postings are never delegated to tools.",
    "release_payment": "Payments are released only by the payment service after its controls.",
    "approve_loan": "Credit decisions belong to authorized underwriters and the committee.",
    "modify_customer": "Customer records are changed only through the customer service.",
}
