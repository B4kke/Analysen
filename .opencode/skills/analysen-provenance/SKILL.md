---
name: Analysen provenance
description: Enforce immutable source-to-claim provenance across raw snapshots, documents, evidence, claims, entity relations and report citations.
---

# Canonical chain

`Source fetch -> raw snapshot -> Document -> Evidence -> Claim -> ClaimEvidence -> Verification -> Report citation`

Every material claim must be traceable backwards without relying on model memory.

# Rules

- Store the fetched payload/content bytes or canonical textual representation, not just the URL.
- Hash the same bytes that are persisted.
- Raw snapshots are immutable and content-addressed.
- Search snippets are discovery only.
- Evidence must contain a locator: JSON pointer, page/region, table cell or excerpt anchor.
- Claims without evidence remain UNVERIFIED/INSUFFICIENT, never silently supported.
- Entity relations need evidence, not just similarity.
- Model rationale is metadata, not evidence.
- Citation UI must be able to retrieve document metadata, snapshot hash and evidence locator.

# Tests

Include a roundtrip assertion that recomputes SHA-256 from stored raw bytes and follows IDs from claim back to document/source.
