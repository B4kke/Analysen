# API-kontrakt — planlagt v1

Base: `/api/v1`

## Investigations
- `POST /investigations`
- `GET /investigations/{id}`
- `POST /investigations/{id}/run`
- `POST /investigations/{id}/pause`
- `POST /investigations/{id}/resume`
- `GET /investigations/{id}/events` (SSE)

## Entities/graph
- `GET /investigations/{id}/entities`
- `GET /investigations/{id}/graph`
- `GET /entities/{entity_id}`
- `POST /entities/{id}/merge`
- `POST /entities/{id}/split`

## Claims/evidence
- `GET /investigations/{id}/claims`
- `GET /claims/{id}`
- `GET /evidence/{id}`

## Reports
- `POST /investigations/{id}/reports`
- `GET /reports/{id}`
- `GET /reports/{id}.html`
- PDF kommer etter HTML renderer.

## Sources/admin
- `GET /sources`
- `GET /models`
- `GET /health`

Alle write requests bruker typed Pydantic schemas. API returnerer aldri secrets/raw internal model reasoning.
