"""A definition as a drawable graph (Phase 21): steps placed in layers, routes labelled,
with live metrics and the latest generated tests' coverage laid over it.

The layout is a small layered (Sugiyama-style) one, computed here so that every client
draws the same picture and it can be tested: routes that lead back to an earlier step are
marked `back` and left out of the layering; each step's layer is its longest distance from
the start along the remaining routes; steps within a layer are ordered by repeated
barycentre sweeps to reduce crossings.
"""

from typing import Any

from pydantic import BaseModel

from app.modules.workflows import library
from app.modules.workflows.definition import Condition, StepType, WorkflowDefinition
from app.modules.workflows.testing import Route, routes

SWEEPS = 4


class GraphNode(BaseModel):
    id: str
    name: str
    type: str
    layer: int
    order: int
    start: bool
    handler: str | None = None
    effect: str | None = None  # library handlers: reads, writes, moves_money, advisory
    outcome: str | None = None
    permissions: list[str] = []
    reachable: bool = True
    # Live executions (code and stored workflows alike).
    runs: int | None = None
    failed: int | None = None
    p95_ms: float | None = None
    bottleneck: bool = False


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str
    label: str
    route: str  # the route's label in generated-test reports
    back: bool = False
    covered: bool | None = None  # by the latest generated tests; None: never tested


class GraphOut(BaseModel):
    workflow_id: str
    version: int
    layers: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    tested_at: str | None = None


def _describe(condition: Condition) -> str:
    if condition.all is not None:
        text = " and ".join(_describe(c) for c in condition.all)
    elif condition.any is not None:
        text = " or ".join(_describe(c) for c in condition.any)
    else:
        symbol = {"eq": "=", "ne": "≠", "in": "in", "not_in": "not in", "gt": ">", "gte": "≥",
                  "lt": "<", "lte": "≤"}.get(condition.op or "", condition.op or "")  # fmt: skip
        if condition.op in ("truthy", "exists"):
            text = f"{condition.path} {condition.op}"
        else:
            value = condition.value
            shown = ", ".join(map(str, value)) if isinstance(value, list) else value
            text = f"{condition.path} {symbol} {shown}"
    return f"not ({text})" if condition.negate else text


def _approves(step_id: str, condition: Condition | None) -> bool:
    from app.modules.workflows.validation import _approves as approves

    return approves(step_id, condition)


def _label(d: WorkflowDefinition, route: Route) -> str:
    step = next(s for s in d.steps if s.id == route.source)
    if route.kind == "failure":
        return "on failure"
    if route.kind == "timeout":
        return f"timeout ({step.timeout.after_seconds // 3600} h)" if step.timeout else "timeout"
    if route.kind in ("branch", "join"):
        return route.kind
    if route.kind == "transition":
        when = step.transitions[route.index].when
        if step.type == StepType.APPROVAL and _approves(step.id, when):
            return "approved"
        return _describe(when) if when is not None else ""
    if step.type == StepType.APPROVAL:
        return "rejected"
    return "otherwise" if step.transitions else ""


def _back_edges(d: WorkflowDefinition, all_routes: list[Route]) -> set[Route]:
    outgoing: dict[str, list[Route]] = {}
    for r in all_routes:
        outgoing.setdefault(r.source, []).append(r)
    back: set[Route] = set()
    state: dict[str, int] = {}  # 1 on the stack, 2 done

    def visit(node: str) -> None:
        state[node] = 1
        for r in outgoing.get(node, []):
            if state.get(r.target) == 1:
                back.add(r)
            elif r.target not in state:
                visit(r.target)
        state[node] = 2

    visit(d.start)
    for s in d.steps:  # unreachable parts too
        if s.id not in state:
            visit(s.id)
    return back


def layout(d: WorkflowDefinition) -> GraphOut:
    ids = [s.id for s in d.steps]
    all_routes = [r for r in routes(d) if r.target in ids]
    back = _back_edges(d, all_routes)
    forward = [r for r in all_routes if r not in back]

    # Longest-path layering over the forward routes (a DAG).
    incoming: dict[str, list[str]] = {i: [] for i in ids}
    for r in forward:
        incoming[r.target].append(r.source)
    layer: dict[str, int] = {}

    def depth(node: str, trail: frozenset[str] = frozenset()) -> int:
        if node in layer:
            return layer[node]
        sources = [s for s in incoming[node] if s not in trail]
        layer[node] = 0 if node == d.start or not sources else (
            1 + max(depth(s, trail | {node}) for s in sources)
        )  # fmt: skip
        return layer[node]

    for i in ids:
        depth(i)
    reachable = _reachable(d, all_routes)

    # Within each layer, order by barycentre of neighbours, alternating directions.
    by_layer: dict[int, list[str]] = {}
    for i in ids:
        by_layer.setdefault(layer[i], []).append(i)
    position = {i: n for nodes in by_layer.values() for n, i in enumerate(nodes)}
    neighbours_up = {i: [r.source for r in forward if r.target == i] for i in ids}
    neighbours_down = {i: [r.target for r in forward if r.source == i] for i in ids}
    for sweep in range(SWEEPS):
        layers = sorted(by_layer) if sweep % 2 == 0 else sorted(by_layer, reverse=True)
        neighbours = neighbours_up if sweep % 2 == 0 else neighbours_down
        for number in layers:
            nodes = by_layer[number]

            def centre(node: str, neighbours: dict[str, list[str]] = neighbours) -> float:
                linked = [position[n] for n in neighbours[node]]
                return sum(linked) / len(linked) if linked else position[node]

            nodes.sort(key=lambda n: (centre(n), position[n]))
            for n, node in enumerate(nodes):
                position[node] = n

    nodes: list[GraphNode] = []
    for s in d.steps:
        handler = library.get(s.handler or "")
        nodes.append(
            GraphNode(
                id=s.id,
                name=s.name,
                type=s.type.value,
                layer=layer[s.id],
                order=position[s.id],
                start=s.id == d.start,
                handler=s.handler,
                effect=handler.effect if handler else None,
                outcome=s.outcome,
                permissions=list(s.approval.permissions) if s.approval else [],
                reachable=s.id in reachable,
            )
        )
    edges = [
        GraphEdge(
            source=r.source,
            target=r.target,
            kind=r.kind,
            label=_label(d, r),
            route=r.label,
            back=r in back,
        )  # fmt: skip
        for r in all_routes
    ]
    return GraphOut(
        workflow_id=d.workflow_id,
        version=d.version,
        layers=max(layer.values(), default=0) + 1,
        nodes=nodes,
        edges=edges,
    )


def _reachable(d: WorkflowDefinition, all_routes: list[Route]) -> set[str]:
    seen, stack = set(), [d.start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(r.target for r in all_routes if r.source == node)
    return seen


def overlay(graph: GraphOut, metrics: Any | None, test_run: Any | None) -> GraphOut:
    """Lay live step metrics and the latest test run's coverage over a layout."""
    if metrics is not None:
        by_step = {m.step_id: m for m in metrics.steps}
        for node in graph.nodes:
            found = by_step.get(node.id)
            node.runs = found.runs if found else 0
            node.failed = found.failed if found else 0
            node.p95_ms = found.p95_ms if found else None
            node.bottleneck = metrics.bottleneck_step == node.id
    if test_run is not None:
        gaps = {u["route"] for u in test_run.uncovered}
        for edge in graph.edges:
            edge.covered = edge.route not in gaps
        graph.tested_at = test_run.ran_at.isoformat()
    return graph
