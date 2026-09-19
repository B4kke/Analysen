# Prosjektstruktur

```text
Analysen/
├── apps/
│   ├── api/app/
│   │   ├── api/routes/         HTTP-kontrakter og execution gates
│   │   ├── core/               settings, YAML-validering, database/readiness
│   │   ├── domain/             typed mål, scope, leads og coverage
│   │   ├── repositories/       PostgreSQL-transaksjoner og audit
│   │   ├── providers/          NIM-provider
│   │   ├── services/           deterministisk domene-/policylogikk
│   │   └── sources/            adapters for eksterne kilder
│   ├── worker/app/             Dramatiq/Redis og bakgrunnsjobber
│   └── web/                   Next.js, undersøkelsesskjema og leseflate
├── config/                    modeller, kilder, policy og SearXNG
├── db/migrations/             Alembic og frosne SQL-revisjoner
├── db/schema.sql              lesbar skjemaoversikt
├── docker/                    separate API-/web-bygg
├── prompts/                   versjonerte LLM-kontrakter
├── tests/integration/         ekte PostgreSQL + API, eksterne adapters erstattes
├── tests/                     deterministiske unit-/kontrakttester
├── docs/                      arkitektur, beslutninger, arbeidskø, drift
├── .github/workflows/ci.yml
├── alembic.ini
├── docker-compose.yml
├── requirements*.lock         låste runtime/dev/research-avhengigheter
└── Makefile
```

API eier database og domene. Web bruker HTTP-kontrakten og deler ingen databaselegitimasjon. Worker gjenbruker domene/services/repositories. SQL-migreringer eies av én koordinator; historiske migreringer endres ikke etter utrulling. PostgreSQL er autoritativt; Redis er kø/cache. Ingen direkte kobling fra LLM til database eller eksterne verktøy uten deterministisk gate.
