# Analysen

Analysen er en kildebevisst OSINT- og bakgrunnsanalysemotor med Norge som primært bruksområde. Systemet skal undersøke personer, virksomheter og relasjoner ved å bruke lovlig tilgjengelige åpne kilder, følge relevante spor innen eksplisitt valgt scope, verifisere funn og produsere etterprøvbare rapporter.

> **Kjerneprinsipp:** Brukeren velger scope. LLM foreslår. Policy/scope gate godkjenner. Verktøy henter. Kode beregner. Evidens dokumenterer. Verifikator kontrollerer. Mennesket vurderer.

## Status
Lokal grunnmur: FastAPI, Next.js, PostgreSQL/pgvector, Redis/Dramatiq, SearXNG og Alembic. Web oppretter og åpner reelle investigations. Scope lagres eksplisitt med modulstatus og audit ved endringer. Datakilde-/modell-/policykonfigurasjon valideres ved oppstart.

BRREG-adapters, normalisering, rolleindeks, entity resolution og NIM-provider finnes. Autonom planner/research-loop, komplett evidence-pipeline og rapportgenerering er videre arbeid; se `docs/TASK_QUEUE.md`. UI viser faktisk lagret tilstand og fremstiller ikke uutførte moduler som undersøkt.

## Stack
- Next.js 16.3 / React 19.3 frontend
- FastAPI/Python backend
- PostgreSQL + pgvector canonical store
- Redis + Dramatiq workers
- NVIDIA NIM via OpenAI-kompatibelt API
- SearXNG discovery
- Crawl4AI + Trafilatura + Playwright
- FollowTheMoney-inspirert entitymodell

## NIM-routing
- Workhorse/extraction: `nvidia/nemotron-3.5-lightning-30b-a3b`
- Planner/default reasoning: `nvidia/nemotron-3-super-120b-a12b`
- Deep verification/planning: `nvidia/nemotron-3-ultra-550b-a55b`
- Norwegian/multimodal + vision: `google/gemma-4-31b-it`
- Vision fallback: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`
- Embeddings: `nvidia/nemotron-3-embed-1b`

Kimi K3 er fjernet fra default routing på grunn av observert latency. Se `docs/NIM_MODELS.md`; norske evals er obligatoriske før routing låses.

## Første oppstart
```bash
cp .env.example .env
# NIM_API_KEY trengs bare ved modellkall; .env er valgfri.
docker compose up --build -d
```

Uten Docker:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock
docker compose up -d postgres redis
alembic upgrade head
make dev-api
```

Web kjører på `http://localhost:3000`, API på `http://localhost:8000`, SearXNG på `http://localhost:8080`.

Se [lokal oppstart og migreringer](docs/DEPLOYMENT.md), [prosjektstruktur](docs/PROJECT_STRUCTURE.md) og [testkommandoer](docs/TESTING.md).

## NIM smoke-test
Etter at `NIM_API_KEY` er satt i `.env`:

```bash
make nim-smoke
```

Dette tester Lightning, Super, Ultra og Gemma 4 på en norsk faktasammenstillingsoppgave og skriver latency/resultat. Vision kan testes med:

```bash
python scripts/nim_smoke.py --suite vision --image-url "https://..."
```

Embedding:

```bash
python scripts/nim_smoke.py --suite embedding
```

## Les før utvikling
1. `AGENTS.md`
2. `docs/TASK_QUEUE.md`
3. `docs/IMPLEMENTATION_PLAN.md`
4. `docs/ARCHITECTURE.md`
5. `docs/INVESTIGATION_SCOPE.md`
6. `docs/SEARCH_TRIGGERS.md`
7. `docs/NORWAY_SOURCES.md`
8. `docs/EVIDENCE_PROVENANCE.md`
9. `docs/ENTITY_RESOLUTION.md`
10. `docs/PRIVACY_LEGAL.md`
11. `docs/SECURITY.md`

`docs/OPEN_SOURCE_REPOS.md` og `docs/REFERENCES.md` inneholder verktøy/kilder som ble vurdert.

## Viktige grenser
Analysen skal ikke omgå innlogging, tilgangskontroll, betalingsmurer, CAPTCHA eller private API-er. Systemet skal ikke inferere sensitive egenskaper eller lage en generell person-risikoscore. Opplysninger om straffedommer/lovovertredelser og tilgangsstyrte registre er policy-gatet.

Discovery av en ny person/virksomhet er ikke automatisk tillatelse til å starte full research på den. Scope, expansion policy, konkret information need og policy/budget må tillate videre arbeid.

## Lisens
Ingen prosjektlisens er valgt ennå. Opphavsrett beholdes inntil en lisens eksplisitt legges til.
