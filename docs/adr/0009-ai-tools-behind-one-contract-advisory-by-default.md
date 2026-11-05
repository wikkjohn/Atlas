# ADR 0009: AI tools sit behind one contract and advise; services decide

- **Status:** Accepted
- **Decided in:** Phases 6, 76, 79

## Context
The AI lab tests tools from several providers and versions. A tool's output must not be
able to move money or approve a case on its own. Costs and drift must be measurable.

## Decision
- **One registry.** `app/modules/ai_tools` holds tool versions with JSON Schema
  contracts, behind a provider-independent adapter interface.
- **One invocation path.** A single service enforces allowed actions, validates requests
  and results, applies timeouts, and records every call (hashed, with tokens and cost
  since Phase 76).
- **Workflows reach tools only through `ai_task` steps.** A separate policy step and the
  domain service keep the final decision with an authorized principal.
- **Hosted model providers are off by default** (`ATLAS_AI_PROVIDER_ENABLED`). The default
  adapter is deterministic and local.

## Consequences
- **Benefits:**
  - Experiments compare tools on the same seeds.
  - Guardrails (drift, bias and prompt audit, Phase 79) read one record of calls.
  - No AI output bypasses a control.
- **Costs:**
  - Every tool must state a schema, and every call pays for validation.
  - A real provider's behaviour can still differ from the local adapter's. Guardrails
    measure that difference; they cannot prevent it.

## Evidence
- `backend/app/modules/ai_tools/service.py`
- `backend/app/modules/ai_tools/guardrails.py`
- `docs/ai-testing.md`
