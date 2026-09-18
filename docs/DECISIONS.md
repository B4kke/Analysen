# Architecture decision log

## ADR-001 — PostgreSQL er canonical store
**Status:** accepted. Graph DB er optional projection. Begrunnelse: provenance/claims/transaksjoner passer relasjonelt og unngår dobbel sannhet.

## ADR-002 — Egen orchestrator før stort agentframework
**Status:** accepted. Typed state machine + Pydantic + queue. Framework kan evalueres senere.

## ADR-003 — BRREG bulkroller som norsk reverse-index
**Status:** accepted. Åpent endepunkt med fødselsdato gjør person->rolle-oppslag mulig lokalt uten kommersiell provider. Fødselsnummer-variant er ikke default.

## ADR-004 — NIM tiered routing
**Status:** accepted. Lightning workhorse, Super balanced, Ultra deep verification/planning, Kimi/Nano Omni vision, Nemotron Embed retrieval. Norske evals avgjør endelig routing.

## ADR-005 — No personal risk score
**Status:** accepted. Funn og evidensstater fremfor svart-boks vurdering.

## ADR-006 — Search snippet is not evidence
**Status:** accepted.

## ADR-007 — Native document parsing before VLM
**Status:** accepted. Bedre kost/latency/provenance.

## ADR-008 — Scope-first investigations
**Status:** accepted. Brukeren velger eksplisitt hvilke research-moduler som skal aktiveres. Identitetsavklaring er alltid aktiv som systemhygiene, men discovery av relaterte entities gir ikke automatisk autorisasjon til videre research. Expansion styres av `expansion_policy`, `max_relation_depth`, materialitet, policy og budsjett. Canonical kontrakt: `INVESTIGATION_SCOPE.md`.

## ADR-009 — Trigger-driven follow-up research
**Status:** accepted. Nye søk/actions krever konkret `information_need` og eksplisitt trigger class. Source router foretrekker målrettede/offisielle adapters før bred websearch. Verifier kan foreslå missing-information leads, men kan ikke starte fri research direkte. Canonical kontrakt: `SEARCH_TRIGGERS.md`.

## ADR-010 — Canonical agent task queue
**Status:** accepted. `docs/TASK_QUEUE.md` er eneste kanoniske arbeidskø for AI-agenter; `docs/WORKLOG.md` er append-only milepælhistorikk. Parallelle TODO-lister i tilfeldige dokumenter skal unngås.

## ADR-011 — NB metadata is open discovery; content capture is rights-gated
**Status:** accepted. Nasjonalbibliotekets katalog/fulltekstsøk kan brukes til discovery og bibliografiske metadata, men søkbarhet betyr ikke at OCR/bilde kan persisteres. Adapteren må lese `accessInfo`; default capture-policy tillater bare digitalisert public-domain-materiale uten kjent legal-deposit/geografi/viewability-begrensning. Begrensede treff beholdes som metadata/lenker, ikke som lokalt kopiert innhold.
