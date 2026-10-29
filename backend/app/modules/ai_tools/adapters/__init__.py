"""Adapter registry: the implementations registered tools can reference by `adapter` key."""

from app.modules.ai_tools.adapters.base import AIToolAdapter
from app.modules.ai_tools.adapters.fault_injection import FaultInjectionAdapter
from app.modules.ai_tools.adapters.kyc_assistant import KycAssistantAdapter
from app.modules.ai_tools.adapters.payment_screening import PaymentScreeningAdapter

ADAPTERS: dict[str, AIToolAdapter] = {
    adapter.key: adapter
    for adapter in (KycAssistantAdapter(), PaymentScreeningAdapter(), FaultInjectionAdapter())
}


def get_adapter(key: str) -> AIToolAdapter | None:
    return ADAPTERS.get(key)
