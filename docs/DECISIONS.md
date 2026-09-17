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
