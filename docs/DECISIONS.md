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


## ADR-011 — Migrering før tjenesteoppstart
**Status:** accepted. Alembic erstatter init-only SQL. Frossen baseline adopterer eksisterende schema.sql-databaser uten sletting. Scope-migreringen gir eldre investigations tomt scope og audit. Migreringene er fremoverrettede for å beholde scope-/auditdata; rollback krever backup. Compose skiller migration-jobben fra API/worker.

## ADR-012 — Lokal grunnmur med låste og delte avhengigheter
**Status:** accepted. Runtime/dev installeres fra hver sin lås; crawler-/dokumentpakker ligger i valgfri research-lås. Web bruker npm ci og standalone-bygg. Lokale tjenester binder loopback, ingen modellnøkkel kreves ved oppstart. Auth/RBAC er nødvendig før ekstern drift.

## ADR-014 — Compose uten host bind-mounts
**Status:** accepted. SearXNG bygges fra pinnet upstream-image med versjonert konfigurasjon. API/worker deler navngitt `app_data`-volum. Dette fjerner avhengigheten til WSL distro-mount-integrasjon uten å endre loopback-/scope-regler. Eksisterende `./data` migreres ikke automatisk; backup og eksplisitt kopiering/verifisering kreves, se `DEPLOYMENT.md`.

## ADR-013 — Scope håndheves før investigation-innhenting
**Status:** accepted. Tomt scope betyr ingen research. Scope-endringer og eksisterende BRREG execution gate deler radlås og transaksjon. Ingest av relaterte entities avvises frem til dokumentert relation/materiality-workflow er implementert. UI viser reell lagret modulstatus. Coverage og triggerkontrakter er grunnlag for AQ-005/AQ-006, ikke automatisk research.
