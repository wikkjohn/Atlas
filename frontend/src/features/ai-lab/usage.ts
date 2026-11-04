/** A hosted model's call (Phase 76): what it cost and its tokens. Rule sets report none. */
export function usageCost(usage: Record<string, unknown> | null | undefined): string {
  const cost = usage?.cost_usd;
  if (typeof cost !== "number") return "—";
  const tokens = Number(usage?.input_tokens ?? 0) + Number(usage?.output_tokens ?? 0);
  return `$${cost.toFixed(4)} · ${tokens.toLocaleString("en-US")} tokens`;
}
