"""Phase 76: a hosted Claude model behind the standard tool contract.

No test calls the real API: the SDK client is replaced by a fake whose "model" answers with
the leave rule set's own decision, so a run with it can be compared case for case.
"""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.adapters import claude
from app.modules.ai_tools.adapters.leave_review import (
    LeaveReviewConfig,
    LeaveReviewInput,
    analyze,
)
from app.modules.ai_tools.models import AIToolInvocation
from app.modules.ai_tools.service import find_tool, invoke
from app.modules.experiments.assumptions import CostAssumptions
from app.modules.experiments.evaluation import costs
from app.modules.experiments.measurements import measure
from app.simulation.models import SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from tests.factories import make_user
from tests.test_leave_review import SCENARIO, _setup, factory  # noqa: F401  (fixture)

PROFILE = {
    "kind": "annual",
    "days": 3,
    "notice_days": 21,
    "annual_balance_after": 12,
    "department_headcount": 5,
    "others_away": 2,
    "coverage_pct": 40,
    "sick_days_365": 0,
    "prior_requests_90d": 0,
    "prior_short_notice_90d": 0,
}
# 1,200 input and 300 output tokens at Claude Opus 5.5's $4 / $20 per million.
CALL_COST = 0.0108


def message(output, *, stop="end_turn", model="claude-opus-5-5", category=None):
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text", text=output if isinstance(output, str) else json.dumps(output)
            )
        ],  # fmt: skip
        stop_reason=stop,
        stop_details=SimpleNamespace(category=category) if category else None,
        model=model,
        usage=SimpleNamespace(
            input_tokens=1200,
            output_tokens=300,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),  # fmt: skip
        _request_id="req_test",
    )


def rule_answer(params: dict) -> SimpleNamespace:
    """A stand-in model: the rule set's own answer to the request it was sent."""
    content = params["messages"][0]["content"]
    payload = json.loads(content.split("Input (JSON):\n", 1)[1])
    result, _ = analyze(LeaveReviewInput.model_validate(payload), LeaveReviewConfig())
    return message(result.model_dump(mode="json"))


class FakeMessages:
    def __init__(self, respond) -> None:
        self.respond, self.calls = respond, []

    async def create(self, **params):
        self.calls.append(params)
        answer = self.respond(params)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def provider(monkeypatch):
    """Hosted calls switched on, with a fake client; `.respond` sets the answer."""
    fake = FakeMessages(rule_answer)
    monkeypatch.setattr(claude, "get_settings", lambda: SimpleNamespace(ai_provider_enabled=True))
    monkeypatch.setattr(claude, "client_factory", lambda config: SimpleNamespace(
        beta=SimpleNamespace(messages=fake)))  # fmt: skip
    return fake


def _tool(db: Session):
    _setup(db)  # registers WF-1044 and the demo tools from the seed's specs
    from app.modules.ai_tools.schemas import ToolCreate
    from app.modules.ai_tools.service import register_tool
    from app.seed import DEMO_AI_TOOLS

    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-leave-assistant-claude")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    db.flush()
    return find_tool(db, "agb-leave-assistant-claude")


def _call(db: Session, tool):
    return invoke(db, tool, "recommend_decision", {"profile": PROFILE}, actor_id=None)


def test_hosted_calls_are_off_unless_switched_on(db: Session, monkeypatch) -> None:
    tool = _tool(db)
    assert tool.adapter == "claude_messages" and tool.configuration["model"] == "claude-opus-5-5"

    def no_client(config):
        raise AssertionError("no client may be built while calls are switched off")

    monkeypatch.setattr(claude, "client_factory", no_client)
    call = _call(db, tool)
    assert call.status == "failed" and call.error["code"] == "provider_disabled"


def test_a_call_keeps_the_tool_contract_and_records_its_cost(db: Session, provider) -> None:
    tool = _tool(db)
    call = _call(db, tool)
    assert call.status == "succeeded", call.error
    assert call.output["recommendation"] == "reject"  # 40 % cover: under-staffed
    assert {f["code"] for f in call.output["findings"]} == {"understaffed"}
    assert call.usage["cost_usd"] == CALL_COST and call.usage["priced"] is True
    assert (call.usage["input_tokens"], call.usage["output_tokens"]) == (1200, 300)
    assert call.usage["model"] == "claude-opus-5-5" and call.usage["request_id"] == "req_test"

    (sent,) = provider.calls
    assert sent["model"] == "claude-opus-5-5"
    assert sent["output_config"]["effort"] == "medium"
    assert (sent["betas"], sent["fallbacks"]) == ([claude.FALLBACK_BETA], "default")
    assert "synthetic" in sent["system"] and "60 %" in sent["system"]
    assert json.loads(sent["messages"][0]["content"].split("Input (JSON):\n")[1]) == {
        "profile": PROFILE
    }
    schema = sent["output_config"]["format"]["schema"]
    text = json.dumps(schema)
    # The registered schema, as structured outputs accept it: closed objects, no limits.
    assert '"minimum"' not in text and '"maximum"' not in text
    assert schema["additionalProperties"] is False
    assert all(d["additionalProperties"] is False for d in schema["$defs"].values()
               if d.get("type") == "object")  # fmt: skip
    assert set(schema["required"]) >= {"recommendation", "confidence", "explanation"}


@pytest.mark.parametrize(
    ("answer", "status", "code"),
    [
        (message({}, stop="refusal", category="cyber"), "failed", "refused"),
        (message('{"recommendation": "app', stop="max_tokens"), "failed", "truncated"),
        (message("I would approve it."), "failed", "unparseable_output"),
        # Valid JSON outside the registered schema: caught by the invocation service.
        (message({"recommendation": "maybe"}), "invalid_output", "invalid_output"),
    ],
)
def test_failed_answers_are_recorded_with_what_they_cost(
    db: Session, provider, answer, status: str, code: str
) -> None:
    tool = _tool(db)
    provider.respond = lambda params: answer
    call = _call(db, tool)
    assert (call.status, call.error["code"]) == (status, code)
    # The provider bills refused and cut-off answers too.
    assert call.usage["cost_usd"] == CALL_COST


def _request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (
            anthropic.RateLimitError(
                "slow down", response=httpx2.Response(429, request=_request()), body=None
            ),
            "rate_limited",
            True,
        ),  # fmt: skip
        (anthropic.APITimeoutError(request=_request()), "provider_timeout", True),
        (anthropic.APIConnectionError(request=_request()), "provider_unreachable", True),
        (
            anthropic.AuthenticationError(
                "bad key", response=httpx2.Response(401, request=_request()), body=None
            ),
            "provider_auth",
            False,
        ),  # fmt: skip
        (
            anthropic.InternalServerError(
                "boom", response=httpx2.Response(529, request=_request()), body=None
            ),
            "provider_error",
            True,
        ),  # fmt: skip
    ],
)
def test_provider_errors_become_structured_failures(
    db: Session, provider, error, code: str, retryable: bool
) -> None:
    tool = _tool(db)
    provider.respond = lambda params: error
    call = _call(db, tool)
    assert call.status == "failed"
    assert (call.error["code"], call.error["retryable"]) == (code, retryable)


def test_cost_at_list_prices() -> None:
    config = claude.ClaudeConfig(instructions="Review the request carefully, please.")
    million = {"input_tokens": 1_000_000}
    assert claude.cost_usd("claude-opus-5-5", million, config) == 4.0
    assert claude.cost_usd("claude-opus-5-5", {"output_tokens": 1_000_000}, config) == 20.0
    assert claude.cost_usd("claude-opus-5-5", {"cache_read_input_tokens": 1_000_000},
                           config) == 0.2  # fmt: skip
    assert claude.cost_usd("claude-opus-5-5", {"cache_creation_input_tokens": 1_000_000},
                           config) == 5.0  # fmt: skip
    # A fallback served by another model is priced at that model's rates.
    assert claude.cost_usd("claude-opus-4-8", million, config) == 5.0
    assert claude.cost_usd("claude-unknown-9", million, config) is None
    own = config.model_copy(update={"input_price_per_mtok": 3.0})
    assert claude.cost_usd("claude-opus-5-5", million, own) == 3.0


def test_a_leave_experiment_counts_what_the_model_cost(db: Session, factory, provider) -> None:  # noqa: F811
    tool = _tool(db)
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    rule_tool = find_tool(db, "agb-leave-assistant")
    runs = []
    for used in (rule_tool, tool):
        run = create_run(
            db, SCENARIO, profile="custom", applications=24, employees=8, seed=17,
            created_by=creator.id, mode="ai_assisted", tool=used,
        )  # fmt: skip
        db.commit()
        execute_run(factory, run.id)
        db.expire_all()
        runs.append(db.get(SimulationRun, run.id))
    rules, hosted = runs
    assert rules.status == hosted.status == SimulationStatus.COMPLETED, hosted.failure_reason
    # The stand-in model gives the rule set's answers, so every case goes the same way.
    assert hosted.results["outcomes"] == rules.results["outcomes"]

    calls = db.execute(
        select(func.count()).where(
            AIToolInvocation.simulation_run_id == hosted.id, AIToolInvocation.status == "succeeded"
        )  # fmt: skip
    ).scalar_one()
    assert calls == len(provider.calls) > 0
    measured = measure(db, hosted)["ai"]
    assert measured["priced_invocations"] == measured["executed_invocations"] == calls
    assert measured["measured_cost"] == pytest.approx(calls * CALL_COST)
    assert measured["input_tokens"] == calls * 1200
    assumptions = CostAssumptions(ai_cost_per_invocation=0.04)
    hosted_cost = costs(measure(db, hosted), assumptions)
    rules_cost = costs(measure(db, rules), assumptions)
    assert hosted_cost["lines"]["ai_execution"] == round(calls * CALL_COST, 2)
    assert hosted_cost["inputs"]["priced_ai_invocations"] == calls
    # Rule-based calls report no cost: they stay on the assumed cost per call.
    assert "priced_invocations" not in measure(db, rules)["ai"]
    assert rules_cost["lines"]["ai_execution"] == round(
        measure(db, rules)["ai"]["executed_invocations"] * 0.04, 2
    )
