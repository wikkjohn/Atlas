"""Adapter registry: the implementations registered tools can reference by `adapter` key."""

from app.modules.ai_tools.adapters.back_office_check import BackOfficeCheckAdapter
from app.modules.ai_tools.adapters.base import AIToolAdapter
from app.modules.ai_tools.adapters.card_fraud import CardFraudAdapter
from app.modules.ai_tools.adapters.covenant_review import CovenantReviewAdapter
from app.modules.ai_tools.adapters.credit_underwriting import CreditUnderwritingAdapter
from app.modules.ai_tools.adapters.document_check import DocumentCheckAdapter
from app.modules.ai_tools.adapters.fault_injection import FaultInjectionAdapter
from app.modules.ai_tools.adapters.kyc_assistant import KycAssistantAdapter
from app.modules.ai_tools.adapters.mortgage_underwriting import MortgageUnderwritingAdapter
from app.modules.ai_tools.adapters.overdraft_affordability import OverdraftAffordabilityAdapter
from app.modules.ai_tools.adapters.payment_screening import PaymentScreeningAdapter
from app.modules.ai_tools.adapters.recall_review import RecallReviewAdapter
from app.modules.ai_tools.adapters.suitability_review import SuitabilityReviewAdapter

ADAPTERS: dict[str, AIToolAdapter] = {
    adapter.key: adapter
    for adapter in (
        KycAssistantAdapter(),
        PaymentScreeningAdapter(),
        CreditUnderwritingAdapter(),
        OverdraftAffordabilityAdapter(),
        CardFraudAdapter(),
        MortgageUnderwritingAdapter(),
        CovenantReviewAdapter(),
        DocumentCheckAdapter(),
        BackOfficeCheckAdapter(),
        RecallReviewAdapter(),
        SuitabilityReviewAdapter(),
        FaultInjectionAdapter(),
    )
}


def get_adapter(key: str) -> AIToolAdapter | None:
    return ADAPTERS.get(key)
