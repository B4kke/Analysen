---
name: Analysen verification
description: Verify claims against concrete evidence, detect contradictions, create typed missing-information needs and enforce citation gates before reviewed/final reporting.
---

# Verification contract

Input:
- claim ID and structured claim,
- explicit evidence IDs/content locators,
- source strength/context,
- optionally competing claims.

Output is schema-valid:
- status,
- supporting evidence IDs,
- contradicting evidence IDs,
- concise rationale,
- typed missing_information items.

Allowed semantic statuses must be consistent across Pydantic, SQL and report code.

# Rules

- No evidence means no supported claim.
- Contradiction handling should seek targeted disconfirmation.
- Missing information is not a direct web-search command; it goes through trigger/scope admission.
- Model explanations are not evidence.
- Invalid model output fails closed.
- Reviewed/final reports reject material claims that lack evidence entailment.
