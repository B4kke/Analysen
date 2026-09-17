# Deployment

## Lokal utvikling
Mål: WSL2/Linux + Docker Compose. Tjenester: postgres/pgvector, redis, searxng, api, worker, web.

NVIDIA NIM brukes primært som hosted API; self-hosting av store NIM-modeller krever NVIDIA-hardware og er ikke en MVP-forutsetning.

## Miljøvariabler
Se `.env.example`. Secrets skal ikke ligge i repo.

## Produksjon senere
- web/API bak reverse proxy/TLS
- egress controls for crawler
- managed/backup PostgreSQL
- object storage med kryptering
- auth/RBAC
- queue workers separat
- audit/metrics

## Portabilitet
Provider abstraction skal tillate lokal modell eller annen OpenAI-kompatibel provider senere uten å endre domain logic.
