---
name: Analysen UI and reporting
description: Keep Next.js/API contracts exact, render real investigation/coverage/claim states, and build evidence-backed Norwegian reports without misleading negative findings.
---

# Contract first

Before UI changes, inspect Pydantic request/response schemas. Arrays remain arrays, enums use exact values, optional values are omitted or typed correctly.

# Investigation UX

Show:
- actual worker/research status,
- module coverage and stop reason,
- admitted/blocked/failed leads where useful,
- claims by verification state,
- evidence/source links,
- target/material/context-only entity distinction.

Never show static "Research er ikke startet" or "Ingen funn" when stored state contradicts it.

# Report pipeline

`verified claims + coverage -> report JSON -> HTML -> PDF`

A report must:
- distinguish investigated vs not investigated,
- distinguish supported/partial/contradicted/insufficient,
- include method/coverage,
- link material findings to evidence,
- avoid treating missing search hits as proof of absence.

Keep mobile behavior as a release gate.
