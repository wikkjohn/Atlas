"""The thin departments' workflows (Phase 61): one stored definition per process, generated
from the registry so that the factory, its generated tests and the simulation see them as
any other example. WF-1100 to WF-1150."""

from typing import Any

from app.modules.backoffice.registry import DEPARTMENTS, Department, Process, workflow_id

RETRY = {"max_attempts": 1, "backoff_seconds": 0}


def _step(id_: str, name: str, handler: str, params: dict, next_: str, failure: str) -> dict:
    return {"id": id_, "type": "service_task", "name": name, "handler": handler,
            "params": params, "retry": RETRY, "on_failure": failure, "next": next_}  # fmt: skip


def document(department: Department, process: Process) -> dict[str, Any]:
    """The stored definition of a process's workflow."""
    properties: dict[str, Any] = {
        "title": {"type": "string", "minLength": 5, "maxLength": 200,
                  "examples": [f"{process.name}: synthetic example"]},
        "details": {"type": "string", "maxLength": 4000,
                    "examples": ["Synthetic request raised by the workflow factory."]},
    }  # fmt: skip
    required = ["title"]
    submit = {"department": department.code, "process": process.code,
              "title_path": "input.title", "details_path": "input.details"}  # fmt: skip
    if process.amount_label:
        example = (process.budget_usd or 10_000) * 50  # half the budget, in cents
        properties["amount"] = {"type": "integer", "minimum": 1, "maximum": 10_000_000_000,
                                "examples": [example],
                                "description": f"{process.amount_label}, in US cents"}  # fmt: skip
        required.append("amount")
        submit["amount_path"] = "input.amount"
    ref = {"request_id_path": "submit.request_id"}
    decided = {**ref, "decided_by_path": "approval.actor_id"}
    if process.approval:
        threshold = (
            f" Above US${process.major_above_usd:,} only an executive approves."
            if process.major_above_usd
            else ""
        )
        steps = [
            _step("submit", "Submit the request", "backoffice.submit_request", submit,
                  "approval", "refused"),
            {"id": "approval", "type": "approval", "name": f"Approve: {process.name}",
             "description": "Someone other than the requester decides the request." + threshold,
             "approval": {"permissions": ["departments:approve"],
                          "distinct_from": ["initiator"]},
             "timeout": {"after_seconds": 86400, "action": "flag"},
             "transitions": [{"to": "approve",
                              "when": {"path": "approval.approved", "op": "truthy"}}],
             "next": "reject"},
            _step("approve", "Approve it", "backoffice.approve_request", decided, "complete",
                  "refused_after"),
            _step("reject", "Reject it", "backoffice.reject_request", decided, "declined",
                  "refused_after"),
            _step("complete", "Complete it", "backoffice.complete_request", ref, "done",
                  "refused_after"),
            {"id": "declined", "type": "completion", "name": "Rejected", "outcome": "rejected"},
        ]  # fmt: skip
        flow = "Someone other than the requester (departments:approve) approves or rejects it."
    else:
        steps = [
            _step(
                "submit",
                "Submit the request",
                "backoffice.submit_request",
                submit,
                "complete",
                "refused",
            ),
            _step(
                "complete",
                "Complete it",
                "backoffice.complete_request",
                ref,
                "done",
                "refused_after",
            ),
        ]
        flow = "It needs no approval."
    steps += [
        {"id": "done", "type": "completion", "name": "Completed", "outcome": "approved"},
        {"id": "refused", "type": "completion", "name": "Refused", "outcome": "rejected"},
        {"id": "refused_after", "type": "completion", "name": "Could not be done",
         "outcome": "rejected"},
    ]  # fmt: skip
    return {
        "workflow_id": workflow_id(department, process),
        "name": f"{department.name}: {process.name}",
        "version": 1,
        "description": f"{process.description} {flow} Target: completed within "
        f"{process.sla_hours} hours. Stored definition generated from the thin-department "
        "registry (Phase 61).",
        "business_owner": department.name,
        "trigger_type": "api",
        "input_schema": {"type": "object", "additionalProperties": False,
                         "required": required, "properties": properties},
        "presentation": {"subject_path": "submit.request_number"},
        "catalogue": {"department": department.name, "tags": ["thin-department"]},
        "start": "submit",
        "steps": steps,
    }  # fmt: skip


def documents() -> list[dict[str, Any]]:
    return [document(d, p) for d in DEPARTMENTS for p in d.processes]
