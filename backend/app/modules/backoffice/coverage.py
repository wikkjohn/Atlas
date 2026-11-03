"""Milestone D coverage (Phase 62): every department with its base processes (stored and
code workflows), its simulation workloads (scenarios) and its dashboard (page).

A workflow's department is its catalogue department where it has one (in its document, or in
the examples' catalogue for `seed-demo`), otherwise its business owner. Older owners named a
department differently; ALIASES maps them onto one name each.
"""

from collections import defaultdict
from typing import Any

# Business owners that predate the department names, and the department each belongs to.
ALIASES = {
    "Retail Banking Operations": "Retail Banking",
    "Retail Banking — Customer Onboarding": "Customer Onboarding",
    "Retail Lending — Collections": "Collections",
}

# The page that is each department's dashboard. The thin departments share one.
DASHBOARDS = {
    "Customer Onboarding": "/customers",
    "Retail Banking": "/retail",
    "Retail Lending": "/lending",
    "Cards": "/cards",
    "Mortgages": "/mortgages",
    "Commercial Lending": "/commercial",
    "Trade Finance": "/trade",
    "Treasury": "/treasury",
    "Payments Operations": "/payment-ops",
    "Wealth Management": "/wealth",
    "Financial Crime Compliance": "/compliance",
    "Credit Risk": "/risk",
    "Finance": "/finance",
    "Customer Service": "/customer-service",
    "Collections": "/collections",
    "Human Resources": "/hr",
    "Procurement": "/procurement",
    "IT Operations": "/it-operations",
}

MIN_PROCESSES = 3


def department_of(document: dict[str, Any], catalogue: dict[str, dict] | None = None) -> str:
    classified = (document.get("catalogue") or {}).get("department")
    if not classified and catalogue:
        classified = (catalogue.get(document["workflow_id"]) or {}).get("department")
    owner = classified or document.get("business_owner") or "Unassigned"
    return ALIASES.get(owner, owner)


def coverage() -> list[dict[str, Any]]:
    """Each department, most processes first: its workflows, scenarios and dashboard, and
    whether it meets the Milestone D bar (three base processes, a workload, a dashboard)."""
    from app.modules.backoffice.registry import DEPARTMENTS
    from app.modules.workflows import examples, registry
    from app.simulation.scenarios import SCENARIOS

    department_of_workflow: dict[str, str] = {}
    for (workflow_id, _), definition in registry._DEFINITIONS.items():
        department_of_workflow[workflow_id] = department_of(
            {"workflow_id": workflow_id, "business_owner": definition.business_owner}
        )
    for document in examples.documents():  # later versions win; they agree on departments
        department_of_workflow[document["workflow_id"]] = department_of(
            document, examples.EXAMPLE_CATALOGUE)  # fmt: skip
    workflows: dict[str, set[str]] = defaultdict(set)
    for workflow_id, department in department_of_workflow.items():
        workflows[department].add(workflow_id)
    scenarios: dict[str, set[str]] = defaultdict(set)
    for (scenario_id, _), scenario in SCENARIOS.items():
        department = department_of_workflow.get(scenario.workflow_id)
        if department:
            scenarios[department].add(scenario_id)
    thin = {d.name for d in DEPARTMENTS}
    rows = []
    for department in sorted(workflows):
        dashboard = "/departments" if department in thin else DASHBOARDS.get(department)
        rows.append({
            "department": department,
            "workflows": sorted(workflows[department]),
            "scenarios": sorted(scenarios[department]),
            "dashboard": dashboard,
            "thin": department in thin,
            "complete": (len(workflows[department]) >= MIN_PROCESSES
                         and bool(scenarios[department]) and dashboard is not None),
        })  # fmt: skip
    return sorted(rows, key=lambda r: (-len(r["workflows"]), r["department"]))
