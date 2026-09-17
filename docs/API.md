# API-kontrakt — v1

Base: `/api/v1`

## Investigations
Implementert:
- `POST /investigations`
- `GET /investigations/{id}`
- `PATCH /investigations/{id}/scope`
- `GET /investigations/{id}/modules`
- `POST /investigations/{id}/sources/brreg/organizations/{orgnr}`

Planlagt:
- `POST /investigations/{id}/run`
- `POST /investigations/{id}/pause`
- `POST /investigations/{id}/resume`
- `GET /investigations/{id}/events` (SSE)
- `GET /investigations/{id}/coverage`

### Create contract
`POST /investigations` støtter:
- `target`
- `purpose`
- `legal_basis_note`
- `scope_modules[]`
- `expansion_policy`
- `max_relation_depth`

Budget-overstyringer er planlagt. Ukjente request-felter avvises. Tomt scope aktiverer ingen research-modul. Person/domain får standard `CONTEXT_ONLY`, dybde 0; company/organization får `DIRECT_RELATIONS`, dybde 1.

Identitetsavklaring er implisitt systemhygiene og ikke en deaktivérbar scope-modul.

### Scope changes
`PATCH /investigations/{id}/scope` krever hele `scope_modules`, `expansion_policy`, `max_relation_depth` og en ikke-tom `reason` (minst 3 tegn), og auditerer utvidelse/innsnevring. Nye actions må umiddelbart følge ny scope-state. Innsnevring sletter ikke eksisterende evidence automatisk.

Ingest-ruten krever aktiv `BUSINESS_ROLES`, enabled kilde og et company/organization-mål med nøyaktig ett `known_orgnrs` som matcher URL-en. Relaterte entities avvises med 403 før nettverkskall. Dette hindrer omgåelse mens scheduler/materiality-workflow gjenstår. GET-moduler viser alle ni moduler med `enabled`, `status`, `coverage` og `stop_reason`; `NOT_STARTED` betyr ikke undersøkt.

## BRREG
Implementert:
- `GET /brreg/search?name=...`
- `GET /brreg/organizations/{orgnr}`
- `GET /brreg/organizations/{orgnr}/roles`
- `GET /brreg/organizations/{orgnr}/legal-roles?size=100&search_after=...`
- `GET /brreg/organizations/{orgnr}/group-structure`
- `GET /brreg/person-roles?name=...&birth_date=YYYY-MM-DD`
- `GET /brreg/role-index/status`

`legal-roles` returnerer også `next_search_after` når siden kan ha flere treff. Klienten sender denne tilbake som `search_after` i neste kall.

## Entities/graph
Planlagt:
- `GET /investigations/{id}/entities`
- `GET /investigations/{id}/graph`
- `GET /entities/{entity_id}`
- `POST /entities/{id}/merge`
- `POST /entities/{id}/split`
- `POST /investigations/{id}/entities/{entity_id}/materiality`

Graph/read models skal eksponere `relation_depth` og `expansion_state` slik at UI kan skille target/material/researched/context-only.

## Claims/evidence
Planlagt:
- `GET /investigations/{id}/claims`
- `GET /claims/{id}`
- `GET /evidence/{id}`
- `GET /investigations/{id}/leads`
- `GET /investigations/{id}/search-queries`

Lead/query read models skal eksponere `scope_area`, `trigger_type/query_class`, `information_need`, `reason`, status og eventuell `blocked_reason`.

## Reports
Planlagt:
- `POST /investigations/{id}/reports`
- `GET /reports/{id}`
- `GET /reports/{id}.html`
- PDF kommer etter HTML renderer.

Report JSON skal inneholde module coverage og eksplisitt skille `UNDERSØKT`, `UNDERSØKT_MED_GAPS`, `IKKE_UNDERSØKT`, `BLOKKERT_UTILGJENGELIG`.

## Sources/admin
- `GET /sources`
- `GET /models`
- `GET /policies`

Uten `/api/v1`-prefiks:
- `GET /health`: 200 for en kjørende prosess.
- `GET /ready`: 200 når PostgreSQL er på gjeldende migreringsversjon og Redis svarer; ellers 503.

`GET /sources` viser global source availability. Dette er ikke det samme som at en source er autorisert i en konkret investigation; scope gate avgjør det.

Alle write requests bruker typed Pydantic schemas. API returnerer aldri secrets eller intern modellresonnering.
