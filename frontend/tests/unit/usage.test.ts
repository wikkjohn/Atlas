import { usageCost } from "@/features/ai-lab/usage";

describe("AI call cost", () => {
  it("shows a hosted model's measured cost and tokens, and nothing for rule sets", () => {
    expect(usageCost({ cost_usd: 0.0108, input_tokens: 1200, output_tokens: 300 })).toBe("$0.0108 · 1,500 tokens");
    expect(usageCost({ rules_evaluated: 5 })).toBe("—");
    expect(usageCost({ cost_usd: null, priced: false })).toBe("—");
    expect(usageCost(undefined)).toBe("—");
  });
});
