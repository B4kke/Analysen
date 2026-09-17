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
