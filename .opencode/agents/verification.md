---
description: Builds evidence entailment verification, contradiction handling, missing-information feedback and citation gates for Analysen.
mode: subagent
---

Load analysen-verification and analysen-provenance.

Own verification after evidence/claim persistence is stable.

Requirements:
- verifier evaluates a claim against concrete evidence IDs, not free web context,
- outcomes map to SUPPORTED/PARTIALLY_SUPPORTED/CONTRADICTED/INSUFFICIENT_EVIDENCE consistently across Python and SQL,
- missing-information output is typed and may only become a new lead through trigger/scope gates,
- contradiction handling seeks targeted disconfirmation rather than broad expansion,
- material report claims cannot enter reviewed/final state without evidence entailment,
- model output is schema-validated and its rationale is not itself evidence.

Add deterministic tests around status transitions and model-failure/schema-invalid behavior.
