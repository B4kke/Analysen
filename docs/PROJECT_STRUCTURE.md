# Prosjektstruktur

```text
Analysen/
├── .github/workflows/ci.yml
├── apps/
│   ├── api/app/
│   │   ├── core/
│   │   ├── domain/
│   │   ├── providers/
│   │   ├── services/
│   │   └── sources/
│   ├── worker/app/
│   └── web/app/
├── config/
│   ├── models.yaml
│   ├── policies.yaml
│   └── sources.yaml
├── db/schema.sql
├── docker/
├── docs/
├── prompts/
├── tests/
├── .env.example
├── docker-compose.yml
├── Makefile
└── README.md
```

Når databasen blir aktivt migrert, flytt `db/schema.sql` til Alembic baseline + migrations uten å miste schema-dokumentasjonen.
