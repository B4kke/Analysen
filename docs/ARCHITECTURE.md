# Arkitektur

## Prinsipp
`user scope -> LLM suggests -> policy/scope gate -> tools retrieve -> code normalizes/calculates -> evidence supports -> verifier checks -> human decides`.

`docs/INVESTIGATION_SCOPE.md` er autoritativ for hva en investigation får undersøke. `docs/SEARCH_TRIGGERS.md` er autoritativ for når og hvorfor systemet får søke videre.

## Logical view
```text
Next.js UI
   |
Investigation scope + expansion policy
   |
FastAPI Investigation API
   |
Orchestrator -----------------------------+
   |                                      |
   +-> Scope Gate / Source Router         |
   |      |                               |
   |      +-> Source adapters -> raw evidence
   |      +-> Search/crawl ----> raw evidence
   |      +-> Documents -------> raw evidence
   |                                      |
                         extraction       |
                             |            |
                      entity resolution   |
                             |            |
              +--------------+---------+  |
              |                        |  |
          entity graph              claims|
              |                        |  |
              +------ lead frontier <--+  |
                          |             |
                    Trigger Evaluator   |
                          |             |
                scope/policy/budget gate|
                          |             |
                    verification -------+
                          |
                  report JSON -> HTML/PDF
```

## Scope gate
Før enhver research-action må scheduler/orchestrator kontrollere:
- aktiv scope-modul,
- expansion policy og relation depth,
- konkret `information_need`,
- policy/tilgang,
- budsjett og dedup/loop-state.

Discovery av en entity gir ikke automatisk rett til å undersøke den videre. Relaterte entities kan beholdes som `CONTEXT_ONLY`.

## Trigger evaluator
Nye funn, konflikter eller manglende evidens kan opprette nye leads gjennom eksplisitte trigger classes i `SEARCH_TRIGGERS.md`. Trigger evaluator skal også kunne konkludere `STOP` når informasjonen er tilstrekkelig, sporet er utenfor scope eller nye treff ikke gir informasjonsverdi.

Verifier kan opprette et målrettet verification lead når en material claim mangler nødvendig evidens. Den skal ikke starte generell bred research på egen hånd.

## Services
### web
Next.js/TypeScript, Tailwind/shadcn, TanStack Query, Cytoscape.js.

### api
FastAPI, Pydantic, SQLAlchemy/asyncpg. Eier domene-API, authorization, investigation scope, policies og read models.

### worker
Købaserte jobs for bulkimport, search, fetch, extract, resolve, verify, analyse og rapport. Jobs mottar eksplisitt scope/module/lead-kontekst.

### PostgreSQL
Canonical state for investigations, scope/module runs, entities, relationships, sources, documents, evidence, claims, leads og audit. pgvector kun for retrieval/candidate generation.

### Redis
Queue, distributed locks, kortvarig cache og rate limiting.

### object/raw store
MVP kan bruke lokalt filvolum. Senere S3/MinIO. Raw evidence adresseres med hash og skal være immutable snapshots.

## State machine
`CREATED -> IDENTIFYING -> RESEARCHING -> VERIFYING -> REPORTING -> REVIEW_REQUIRED -> FINAL`.
Feiltilstander er resumable og jobber skal være idempotente.

Scope-endring er en auditert state-endring som kan åpne/lukke modul-leads uten å slette tidligere evidens automatisk.

## Investigation frontier
Leads har type, value/entity_id, reason, `scope_area`, `trigger_type`, `information_need`, source claim, priority, depth og status. Scheduler velger høyest forventet informasjonsverdi innen scope, policy og budsjett.

## Budgets
Konfigurer per investigation: max depth, max relation depth, max URLs, max per-domain fetches, max wall-clock, max model calls/tokens og max unresolved leads. Budgets finnes for stabilitet selv når API-et er gratis.

## Coverage
Hver aktiv scope-modul fører coverage ledger med kilder/providers forsøkt, query classes, dokumenter, tidsrom, stop reason og kjente gaps. Dette brukes i rapportens metode/søkeomfang.

## Canonical vs projections
PostgreSQL er canonical. Cytoscape-data, embeddings, fulltekstindeks og eventuelle fremtidige graph databases er projections som kan bygges på nytt.

## Provider abstraction
`LLMProvider`, `EmbeddingProvider`, `SearchProvider`, `CrawlerProvider`, `SourceAdapter`, `ObjectStore`. Ingen business logic skal anta én leverandør.


## Implementert grunnmur og videre grenser

Den kjørbare vertikale flyten er `Next.js → FastAPI → scope/audit → PostgreSQL`. `/ready` kontrollerer databaseskjema og Redis. Compose kjører Alembic som en egen oppstartsjobb. Pydantic validerer modell-/kilde-/policy-YAML før API starter. NIM-nøkkel kreves først ved inferens.

Investigations opprettes med eksplisitte moduler (standard ingen). Scope-oppdatering er én transaksjon med before/after-audit og bevaring av eksisterende coverage/evidens. Innhentingsruten låser samme investigation-rad mens autorisasjon og innhenting pågår, slik at scope-endringer og nye actions serialiseres. Urelaterte investigations blokkerer ikke hverandre.

BRREG-ingest tillates foreløpig bare for et entydig company/organization-mål med ett `known_orgnrs` og aktiv `BUSINESS_ROLES`. Generiske BRREG GET-ruter er manuelle registeroppslag, ikke del av en automatisk investigation. Utvidelse til relaterte entities krever senere scheduler/materiality-workflow; discovery eller et oppgitt personnavn gir ingen autorisasjon.

`Lead`, `SearchMetadata`, module coverage og expansion states har typed kontrakter og databasestruktur. Scheduler, trigger evaluator, automatiske coverage-oppdateringer og rapportmotor er fortsatt planlagt. En databasekolonne eller DTO er ikke en ferdig agentflyt.

## Lead admission (AQ-005)

Planner/LLM kan bare foreslå leads via `POST /api/v1/investigations/{id}/leads`. Ruten låser investigation-rad og kjører deterministisk admission i `services/lead_gate.py` før lagring. Passive discovery-triggere (`NEW_VERIFIED_ALIAS`, `MEDIA_CORROBORATION`, `SANCTIONS_CANDIDATE`) lagres aldri som kjørbare; de blir `BLOCKED/passive_trigger_requires_review`. Refuserte leads lagres som `BLOCKED` med gate-årsak og audit; `LEAD_PROPOSED` audit er ikke frivillig — en transaksjon uten audit rulles tilbake. Scope-innsnevring blokkerer fortsatt ventende leads samme transaksjon. Det finnes ingen rute som oppretter `PENDING`-leads utenom gaten; NIM-planneren kobles senere som én av flere forslagsgivere bak samme rute.

## Trigger evaluator, frontier og eksekutor (AQ-012/AQ-013)

`services/trigger_evaluator.py` ruter hvert forslag til én typed beslutning: `FOLLOW_UP_LEAD`, `VERIFICATION_LEAD`, `CONTEXT_ONLY`, `BLOCKED_BY_SCOPE` eller `STOP_*`. Uverifiserte relasjoner og passive triggere blir `CONTEXT_ONLY` — aldri auto-kjøring. Contradiction gir målrettet `VERIFICATION_LEAD` på samme entity. `services/frontier.py` velger høyeste prioritet blant `PENDING`-leads innen dybde og budsjett. `services/lead_executor.py` kjører valgte leads via `POST /investigations/{id}/leads/{lead_id}/execute`: kun allowlisted lead-typer (første: `brreg_organization_lookup` mot eksplisitt mål), gaten sjekkes på nytt ved verktøygrensen, og hvert utfall (COMPLETED/BLOCKED/FAILED) oppdaterer status, coverage og audit. Evaluator, velger og eksekutor er deterministiske og modellfrie.
