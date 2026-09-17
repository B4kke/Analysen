# API-kontrakt — v1

Base: `/api/v1`

## Investigations
- `POST /investigations`
- `GET /investigations/{id}`
- `POST /investigations/{id}/run`
- `POST /investigations/{id}/pause`
- `POST /investigations/{id}/resume`
- `GET /investigations/{id}/events` (SSE)

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

## Claims/evidence
Planlagt:
- `GET /investigations/{id}/claims`
- `GET /claims/{id}`
- `GET /evidence/{id}`

## Reports
Planlagt:
- `POST /investigations/{id}/reports`
- `GET /reports/{id}`
- `GET /reports/{id}.html`
- PDF kommer etter HTML renderer.

## Sources/admin
- `GET /sources`
- `GET /models`
- `GET /policies`
- `GET /health`
- `GET /ready`

Alle write requests bruker typed Pydantic schemas. API returnerer aldri secrets eller intern modellresonnering.
