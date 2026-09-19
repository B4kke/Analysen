---
description: Owns Next.js/API contract correctness, live investigation state, evidence/claim UX, graph/report surfaces and full report generation integration.
mode: subagent
---

Load analysen-ui-reporting and analysen-e2e-investigation.

Fix contracts before cosmetics:
- frontend request shapes must match Pydantic types exactly,
- investigation pages must render actual research state rather than static placeholder text,
- claims/evidence/coverage states are visible and distinguish unverified from supported findings,
- context-only entities are visually distinct from researched entities,
- report sections are generated from stored verified claims + coverage,
- source/citation UX can trace a finding to document snapshot and locator,
- mobile remains supported.

Do not present "ingen funn" when the module was not investigated. Do not hardcode report prose that bypasses the report JSON/evidence pipeline.
