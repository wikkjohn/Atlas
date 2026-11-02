import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo, useState } from "react";
const NODE_W = 184;
const NODE_H = 54;
const COL = 216;
const ROW = 104;
const PAD = 24;
const TYPE_STYLE = {
    service_task: { fill: "#f8fafc", stroke: "#94a3b8" },
    ai_task: { fill: "#f5f3ff", stroke: "#8b5cf6" },
    approval: { fill: "#fffbeb", stroke: "#f59e0b" },
    human_task: { fill: "#fffbeb", stroke: "#f59e0b" },
    decision: { fill: "#eff6ff", stroke: "#3b82f6" },
    wait: { fill: "#f0f9ff", stroke: "#0ea5e9" },
    parallel: { fill: "#f1f5f9", stroke: "#475569" },
    join: { fill: "#f1f5f9", stroke: "#475569" },
    completion: { fill: "#ecfdf5", stroke: "#10b981" },
    failure: { fill: "#fff1f2", stroke: "#f43f5e" },
};
const EFFECT_TEXT = {
    writes: "writes",
    moves_money: "moves money",
    advisory: "AI advice",
};
function edgeColour(edge, coverage) {
    if (coverage && edge.covered === true)
        return "#10b981";
    if (coverage && edge.covered === false)
        return "#f43f5e";
    return "#94a3b8";
}
/** A workflow drawn from the server's layout: steps in layers, routes labelled. */
export function WorkflowGraph({ graph, errors = {}, onSelect, selected, }) {
    const [coverage, setCoverage] = useState(true);
    const tested = graph.edges.some((e) => e.covered !== null && e.covered !== undefined);
    const width = useMemo(() => {
        const perLayer = new Map();
        for (const n of graph.nodes)
            perLayer.set(n.layer, Math.max(perLayer.get(n.layer) ?? 0, n.order + 1));
        return Math.max(...perLayer.values(), 1);
    }, [graph.nodes]);
    const counts = new Map();
    for (const n of graph.nodes)
        counts.set(n.layer, (counts.get(n.layer) ?? 0) + 1);
    const pos = new Map(graph.nodes.map((n) => {
        const offset = ((width - (counts.get(n.layer) ?? 1)) * COL) / 2;
        return [n.id, { x: PAD + offset + n.order * COL, y: PAD + n.layer * ROW }];
    }));
    const svgWidth = PAD * 2 + width * COL;
    const svgHeight = PAD * 2 + graph.layers * ROW;
    const uncovered = graph.edges.filter((e) => e.covered === false).length;
    return (_jsxs("div", { className: "space-y-2", children: [_jsxs("div", { className: "flex flex-wrap items-center gap-3 text-xs text-slate-600", children: [tested ? (_jsxs("label", { className: "flex items-center gap-1.5", children: [_jsx("input", { type: "checkbox", checked: coverage, onChange: (e) => setCoverage(e.target.checked) }), "Test coverage (", uncovered === 0 ? "every route covered" : `${uncovered} route(s) not covered`, ")"] })) : (_jsx("span", { children: "Routes are grey until generated tests have run." })), _jsx("span", { className: "text-slate-400", children: "Numbers on steps: live runs (failed)." })] }), _jsx("div", { className: "overflow-auto rounded-xl border border-slate-200 bg-white", children: _jsxs("svg", { role: "img", "aria-label": `Diagram of ${graph.workflow_id} v${graph.version}`, width: svgWidth, height: svgHeight, viewBox: `0 0 ${svgWidth} ${svgHeight}`, className: "block", children: [_jsx("defs", { children: ["#94a3b8", "#10b981", "#f43f5e"].map((c) => (_jsx("marker", { id: `arrow-${c.slice(1)}`, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse", children: _jsx("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: c }) }, c))) }), graph.edges.map((e) => {
                            const from = pos.get(e.source);
                            const to = pos.get(e.target);
                            if (!from || !to)
                                return null;
                            const colour = edgeColour(e, coverage && tested);
                            let d;
                            let lx;
                            let ly;
                            if (e.back || to.y <= from.y) {
                                // Back to an earlier step: around the right-hand side.
                                const sx = from.x + NODE_W;
                                const sy = from.y + NODE_H / 2;
                                const tx = to.x + NODE_W;
                                const ty = to.y + NODE_H / 2;
                                const bulge = Math.max(sx, tx) + 40;
                                d = `M ${sx} ${sy} C ${bulge} ${sy}, ${bulge} ${ty}, ${tx} ${ty}`;
                                lx = bulge - 8;
                                ly = (sy + ty) / 2;
                            }
                            else {
                                const sx = from.x + NODE_W / 2;
                                const sy = from.y + NODE_H;
                                const tx = to.x + NODE_W / 2;
                                const ty = to.y;
                                const mid = (sy + ty) / 2;
                                d = `M ${sx} ${sy} C ${sx} ${mid}, ${tx} ${mid}, ${tx} ${ty}`;
                                lx = (sx + tx) / 2;
                                ly = mid;
                            }
                            return (_jsxs("g", { "data-route": e.route, "data-covered": String(e.covered ?? ""), children: [_jsx("path", { d: d, fill: "none", stroke: colour, strokeWidth: 1.5, strokeDasharray: coverage && tested && e.covered === false ? "5 4" : e.kind === "failure" || e.kind === "timeout" ? "2 3" : undefined, markerEnd: `url(#arrow-${colour.slice(1)})`, children: _jsx("title", { children: e.route }) }), e.label && (_jsx("text", { x: lx, y: ly, textAnchor: "middle", className: "fill-slate-500", fontSize: 10, paintOrder: "stroke", stroke: "#ffffff", strokeWidth: 3, children: e.label.length > 34 ? `${e.label.slice(0, 33)}…` : e.label }))] }, e.route));
                        }), graph.nodes.map((n) => {
                            const p = pos.get(n.id);
                            const style = TYPE_STYLE[n.type] ?? TYPE_STYLE.service_task;
                            const problem = errors[n.id];
                            const isSelected = selected === n.id;
                            return (_jsxs("g", { "data-step": n.id, transform: `translate(${p.x}, ${p.y})`, onClick: () => onSelect?.(n.id), className: onSelect ? "cursor-pointer" : undefined, opacity: n.reachable ? 1 : 0.5, children: [_jsx("title", { children: `${n.name} (${n.type})${n.handler ? ` · ${n.handler}` : ""}${n.permissions.length ? ` · needs ${n.permissions.join(" + ")}` : ""}${problem ? ` · ${problem.join("; ")}` : ""}` }), _jsx("rect", { width: NODE_W, height: NODE_H, rx: n.type === "decision" ? 2 : 10, fill: problem ? "#fff1f2" : style.fill, stroke: problem ? "#e11d48" : isSelected ? "#0f172a" : n.bottleneck ? "#d97706" : style.stroke, strokeWidth: problem || isSelected || n.bottleneck ? 2.5 : 1.5 }), _jsxs("text", { x: 10, y: 18, fontSize: 9, className: "fill-slate-500", children: [n.start ? "START · " : "", n.type.replace("_", " "), n.effect && EFFECT_TEXT[n.effect] ? ` · ${EFFECT_TEXT[n.effect]}` : "", n.outcome ? ` → ${n.outcome}` : ""] }), _jsx("text", { x: 10, y: 36, fontSize: 12, fontWeight: 600, className: "fill-slate-900", children: n.name.length > 26 ? `${n.name.slice(0, 25)}…` : n.name }), n.runs !== null && n.runs !== undefined && (_jsxs("text", { x: NODE_W - 8, y: 18, fontSize: 9, textAnchor: "end", className: n.failed ? "fill-rose-600" : "fill-slate-400", children: [n.runs, n.failed ? ` (${n.failed})` : ""] })), problem && (_jsxs("text", { x: 10, y: 49, fontSize: 9, className: "fill-rose-700", children: [problem.length, " problem", problem.length > 1 ? "s" : ""] }))] }, n.id));
                        })] }) })] }));
}
