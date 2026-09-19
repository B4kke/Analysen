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

## ADR-017 — Ingen auth på lokalt nettverk
**Status:** accepted. Analysen er et lokalt én-operatør-verktøy på lukket nett. Auth/RBAC bygges ikke: alle tjenester binder loopback, ingen porter eksponeres eksternt, og operatøridentitet er fast `local-operator` i audit. Dersom driftsmodellen noen gang endres til delt/ekstern tilgang, må auth, operatøridentitet og tilgangskontroll leveres først — da som egen oppgave, ikke som tillegg her.

## ADR-016 — Per-sak eksport og auditert sletting
**Status:** accepted. `export_investigation` samler sak, moduler, entities, claims, leads, dokumenter med raw-nøkler og audit i én portabel pakke (raw bytes forblir i object store, referert per hash). `delete_investigation` sletter cascade-eide data i én transaksjon etter `INVESTIGATION_DELETED`-audit; audit-rader overlever via `ON DELETE SET NULL`. Innholdsadresserte raw snapshots deles mellom dokumenter og slettes ikke ved sakssletting. Auth/RBAC og backup/restore er separate leveranser før ekstern drift.

## ADR-015 — Deterministisk lead admission før planner-LLM
**Status:** accepted. Alle planner/LLM-forslag kommer inn gjennom `POST /investigations/{id}/leads` og gate i `lead_gate.py`. Passive discovery-triggere lagres aldri som kjørbare. Refuserte leads lagres `BLOCKED` med årsak for auditbarhet i stedet for å kastes. NIM-planneren blir en forslagsgiver bak samme rute; gaten er modell-uavhengig.

## ADR-014 — Compose uten host bind-mounts
**Status:** accepted. SearXNG bygges fra pinnet upstream-image med versjonert konfigurasjon. API/worker deler navngitt `app_data`-volum. Dette fjerner avhengigheten til WSL distro-mount-integrasjon uten å endre loopback-/scope-regler. Eksisterende `./data` migreres ikke automatisk; backup og eksplisitt kopiering/verifisering kreves, se `DEPLOYMENT.md`.

## ADR-013 — Scope håndheves før investigation-innhenting
**Status:** accepted. Tomt scope betyr ingen research. Scope-endringer og eksisterende BRREG execution gate deler radlås og transaksjon. Ingest av relaterte entities avvises frem til dokumentert relation/materiality-workflow er implementert. UI viser reell lagret modulstatus. Coverage og triggerkontrakter er grunnlag for AQ-005/AQ-006, ikke automatisk research.


## ADR-018 — Canonical claim-status og immutable dokumentprovenance
**Status:** accepted (2026-09-18). `ClaimStatus` er felles vokabular for SQL/Pydantic/repository. Eldre `UNVERIFIED` blir `UNVERIFIED_LEAD`; eldre `VERIFIED` blir `INSUFFICIENT_EVIDENCE` med bevart verdi og evidenskoblinger. Den tidligere implementasjonen hadde ingen entailment-verifier, så en statusetikett eller evidenskobling alene kan ikke oppgradere en eldre påstand til støttet. Gjentatt innhenting av samme snapshot bevarer første kilde, URL og hentetid. Canonical forhold lagres i `relationships`; en eventuell ikke-tom duplikattabell må avklares uten stille sletting.

## ADR-019 — Én kontrollert transport for research-runtime
**Status:** accepted (2026-09-18). API/worker-imaget inkluderer research-lås og Chromium; lett lokal utvikling kan fortsatt bruke dev-låsen alene (presisering av ADR-012). Originale HTTP-bytes lagres før offline-ekstraksjon. Browser-requests oppfylles gjennom samme DNS/IP-pinnede transport med robots, rate, concurrency, størrelses- og requestgrenser. Chromium får ingen selvstendig egress. Renderet HTML er avledet evidence med separat hash.

## ADR-020 — Observér korrelert research-pass og konsistent detalj-snapshot
**Status:** accepted (2026-09-18). Jobb-ID binder REQUESTED/ENQUEUED/STARTED/COMPLETED/FAILED i append-only audit. Faseprioritet innen samme jobb tåler rask worker og sen broker-bekreftelse; en ekte worker-completion veier høyere enn sen dispatch-feil. Valgt terminalevent eier summary, terminaltid og error_code. Nyeste jobb velges etter første audit-event. Legacy/directingest viser registrert aktivitet uten å inventere kø/liveness. Detalj-GET bruker repeatable-read/read-only og no-store for å unngå terminalstatus sammen med claims fra en eldre lesing. Originalkilden tilbys som case-gatet, hash-verifisert attachment. Durable outbox, heartbeat/hard-crash recovery og replay-checkpoints er eksplisitt AQ-023, ikke en implisitt exactly-once-garanti.


## ADR-021 — Nasjonalbiblioteket som mixed-rights direct source
**Status:** accepted (2026-09-18). Nasjonalbiblioteket/DH-lab/IIIF integreres som målrettet direct source for norsk mediaresearch, ikke som generisk SearXNG-resultat. PERSON + aktiv `WEB_MEDIA` kan få et deterministic exact-name NB-seed. Catalog brukes til discovery/item/page metadata, IIIF Content Search til tekstankre/koordinater, og DH-lab `/conc` til begrenset keyword-in-context. NB har item-spesifikke rettigheter: source-level tilgjengelighet gir ikke automatisk fulltekst-/bilde-/republiseringsrett. Dokumentpolicy skal derfor avgjøre metadata/context/fulltext/page/crop/embed separat og fail-closed. Restricted materiale representeres med lovlig kontekst, metadata og direkte NB-link; ingen teknisk bypass. Canonical kontrakt: `docs/NATIONAL_LIBRARY.md`.

## ADR-022 — Executor-toolkontrakt med fail-closed guard
**Status:** accepted (2026-09-19). `ExecutorTools.nb_media_client` er typet mot `NBMediaClient`-protokollen (TYPE_CHECKING-import, ingen runtime-syklus), og `execute_nb_media_lead` avviser klienter uten alle fem capabilities med `executor_unavailable` i stedet for å krasje med `AttributeError` (AQ-024-regelen: manglende verktøy feiler lukket, aldri krasj). Bakgrunn: workeren sendte rå `NationalLibraryClient` der adapter-broen forventes, noe som feilet alle NB-leads med `source_error:AttributeError` i produksjonsflyten mens tester (med korrekt adapter) var grønne. Mypy fanger nå feilkobling statisk; runtime-garden fanger resten.
