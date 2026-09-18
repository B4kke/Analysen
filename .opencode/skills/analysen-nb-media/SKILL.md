---
name: Analysen National Library media
description: Implement and verify Nasjonalbiblioteket newspaper/media research with Catalog, IIIF and DH-lab while preserving provenance, item-level rights, identity uncertainty and report usability.
---

# Canonical document

Read `docs/NATIONAL_LIBRARY.md` before editing this subsystem. It is authoritative for endpoint roles, rights/access semantics, provenance, fixtures and report behavior.

# Mission

Turn a Norwegian person/media information need into evidence-backed newspaper mentions.

Do not stop at publication/date/page metadata when lawful text context or permitted article extraction is available.

# Required chain

```text
target / verified alias
-> deterministic NB direct-source lead
-> Catalog FULL_TEXT_SEARCH
-> raw snapshot
-> issue candidate
-> access normalization
-> page locator
-> IIIF xywh anchors
-> DH-lab concordance
-> MediaMentionCandidate
-> entity resolution
-> rights gate
   -> restricted: context + metadata + NB link
   -> permitted: page -> article crop -> OCR
-> typed extraction
-> Evidence / ClaimCandidate
-> verifier
-> ReportDocument.media_mentions
```

# Endpoint roles

## Catalog search

Use for OCR discovery and item metadata.

Persist the raw response before parsing if it contributes to evidence or coverage.

## contentfragments

Treat as locator only unless upstream actually returns usable lawful context.

Live regression reference: large `fragSize` could still yield only `... <em>target</em> ...`.

Never equate this endpoint with article extraction.

## IIIF Content Search

Parse token/canvas targets and exact `xywh` coordinates.

Store coordinates as provenance locators and use them as anchors for permitted article-region extraction.

## DH-lab /conc

Primary keyword-in-context provider.

Use bounded `window` and `limit`.

Mark returned text `PARTIAL_CONTEXT`.

Never reconstruct a protected full article by stitching many overlapping concordances.

# Direct-source seed

When target is PERSON and `WEB_MEDIA` is selected, create a deterministic, deduplicated NB exact-name lead.

Do not require planner creativity for this baseline lookup.

Verified aliases may seed additional exact-name searches.

Use a semantically correct direct-source/target-level trigger. Do not mislabel initial research as contradiction or weak-source verification.

# Rights policy

NB is mixed-rights.

Persist upstream access fields and normalize per item.

Required outcomes should be equivalent to:
- PUBLIC_REUSE
- PUBLIC_VIEW_ONLY
- LIBRARY_ONLY
- NB_ONLY
- UNKNOWN

Unknown is restrictive.

The policy must decide independently:
- can metadata be stored,
- can concordance/context be stored,
- can full text be stored,
- can page image be fetched,
- can crop be derived,
- can image/crop be embedded in report.

Never infer reuse permission solely from `viewability`.

# Article text

Text availability states:
- FULL
- PARTIAL_CONTEXT
- UNAVAILABLE

FULL requires actual lawful full text.

PARTIAL_CONTEXT is not an article.

# Permitted image/OCR path

When page fetch is explicitly allowed:

1. persist original page bytes immutably,
2. verify hash,
3. anchor on IIIF target coordinates,
4. run pytesseract TSV/data with Norwegian language,
5. locate target-containing line/block,
6. expand conservatively to candidate article region,
7. validate target occurrence,
8. persist crop as derived immutable document,
9. OCR crop,
10. persist parent page/crop geometry.

Use vision model only when deterministic layout/OCR cannot reliably segment the article. Vision output must be typed and treated as derived analysis, not source evidence.

# Network/runtime

Use injectable clients.

Respect project safe transport and access controls where applicable.

No authentication bypass, no hidden browser path around NB restrictions.

Bound retries, page/image sizes and request counts.

# Identity

Same-name media hits start UNRESOLVED.

Use existing entity-resolution system. Do not create a special permissive NB matcher.

Name-only must not reach MATCH/PROBABLE_MATCH above existing configured caps.

# Evidence

Preferred locators:
- nb_catalog_item
- nb_page
- nb_concordance
- image_region
- ocr_region

Preserve:
- item id,
- issue/page URN,
- page number,
- query,
- xywh,
- publication/date,
- access/license metadata,
- hashes.

# Extraction

Typed extraction may produce headline, body, caption, summary, target context and entity/claim candidates.

LLM output is not evidence.

Claims require concrete evidence IDs and existing verifier/citation gates.

# Report

NB output belongs in the canonical report, not a separate report silo.

`ReportDocument.media_mentions` should expose content and access state consistently to JSON, HTML, PDF and Next.js.

Restricted content should render as source/context/link with a clear access explanation, never as a broken image or fabricated full text.

# Testing

CI: fixtures only.

Required tests:
- Catalog parsing,
- page locator behavior,
- contentfragments-not-fulltext regression,
- IIIF xywh parsing,
- concordance PARTIAL_CONTEXT,
- fail-closed rights matrix,
- restricted case cannot call image downloader,
- permitted page/crop/OCR provenance,
- identity remains unresolved on name-only,
- report parity across JSON/HTML/PDF,
- rerun idempotency,
- real PostgreSQL migration/repository roundtrip where schema changes.

Optional live probe:
`scripts/nb_probe.py`

Use Maylen Sorkness Andersen and Eltonåsen only as endpoint-shape diagnostics. Do not make CI depend on mutable live counts.
