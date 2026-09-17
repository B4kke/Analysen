# Arkitektur

## Prinsipp
`LLM suggests -> tools retrieve -> code normalizes/calculates -> evidence supports -> verifier checks -> human decides`.

## Logical view
```text
Next.js UI
   |
FastAPI Investigation API
   |
Orchestrator -----------------------------+
   |                                      |
   +-> Source adapters -> raw evidence    |
   +-> Search/crawl ----> raw evidence    |
   +-> Documents -------> raw evidence    |
                         |                |
                  extraction              |
                         |                |
                  entity resolution       |
                         |                |
           +-------------+-------------+  |
           |                           |  |
       entity graph                claims |
           |                           |  |
           +--------- lead frontier <-+  |
                         |                |
                    verification ---------+
                         |
                  report JSON -> HTML/PDF
```

## Services
### web
Next.js/TypeScript, Tailwind/shadcn, TanStack Query, Cytoscape.js.

### api
FastAPI, Pydantic, SQLAlchemy/asyncpg. Eier domene-API, authorization, investigations og read models.

### worker
Købaserte jobs for bulkimport, search, fetch, extract, resolve, verify, analyse og rapport.

### PostgreSQL
Canonical state for investigations, entities, relationships, sources, documents, evidence, claims, leads og audit. pgvector kun for retrieval/candidate generation.

### Redis
Queue, distributed locks, kortvarig cache og rate limiting.

### object/raw store
MVP kan bruke lokalt filvolum. Senere S3/MinIO. Raw evidence adresseres med hash og skal være immutable snapshots.

## State machine
`CREATED -> IDENTIFYING -> RESEARCHING -> VERIFYING -> REPORTING -> REVIEW_REQUIRED -> FINAL`.
Feiltilstander er resumable og jobber skal være idempotente.

## Investigation frontier
Leads har type, value/entity_id, reason, source claim, priority, depth og status. Scheduler velger høyest forventet informasjonsverdi innen budsjett.

## Budgets
Konfigurer per investigation: max depth, max URLs, max per-domain fetches, max wall-clock, max model calls/tokens og max unresolved leads. Budgets finnes for stabilitet selv når API-et er gratis.

## Canonical vs projections
PostgreSQL er canonical. Cytoscape-data, embeddings, fulltekstindeks og eventuelle fremtidige graph databases er projections som kan bygges på nytt.

## Provider abstraction
`LLMProvider`, `EmbeddingProvider`, `SearchProvider`, `CrawlerProvider`, `SourceAdapter`, `ObjectStore`. Ingen business logic skal anta én leverandør.
