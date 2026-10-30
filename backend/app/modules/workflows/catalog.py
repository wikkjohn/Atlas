"""Imports every business workflow so its definitions and handlers are registered, and the
handler library that stored definitions use; classifies the code workflows (Phase 22)."""

from app.modules.workflows import library, wf0001, wf0002, wf0003, wf0004  # noqa: F401
from app.modules.workflows.definition import Catalogue
from app.modules.workflows.registry import register_catalogue

DEMO_COUNTRIES = ["DE", "GB", "JP", "SG", "US"]

register_catalogue(
    "WF-0001",
    Catalogue(
        department="Customer Onboarding",
        countries=DEMO_COUNTRIES,
        products=["current", "savings"],
        tags=["onboarding", "kyc", "ai"],
    ),
)
register_catalogue(
    "WF-0002",
    Catalogue(
        department="Payments Operations",
        countries=DEMO_COUNTRIES,
        products=["domestic_payment"],
        tags=["payments", "fraud"],
    ),
)
register_catalogue(
    "WF-0003",
    Catalogue(
        department="Lending",
        countries=DEMO_COUNTRIES,
        products=["personal_loan"],
        tags=["lending", "underwriting", "ai"],
    ),
)
register_catalogue(
    "WF-0004",
    Catalogue(
        department="Collections",
        countries=DEMO_COUNTRIES,
        products=["personal_loan"],
        tags=["collections", "arrears"],
    ),
)
