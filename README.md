# Analysen

Analysen er en kildebevisst OSINT- og bakgrunnsanalysemotor med Norge som primært bruksområde. Systemet skal undersøke personer, virksomheter og relasjoner ved å bruke lovlig tilgjengelige åpne kilder, følge nye spor, verifisere funn og produsere etterprøvbare rapporter.

> **Kjerneprinsipp:** LLM foreslår. Verktøy henter. Kode beregner. Evidens dokumenterer. Verifikator kontrollerer. Mennesket vurderer.

## Status

Prosjektet er i arkitektur- og grunnmursfasen. Første mål er en norsk MVP med Brønnøysundregistrene, Regnskapsregisteret, SearXNG, web-crawling, entity resolution, evidenslager og NVIDIA NIM.

## Hovedkomponenter

- Next.js/TypeScript frontend
- FastAPI/Python backend
- PostgreSQL + pgvector som canonical store
- Redis + worker-kø
- NVIDIA NIM via OpenAI-kompatibelt API
- SearXNG for discovery
- Crawl4AI + Trafilatura + Playwright for innhenting
- FollowTheMoney-inspirert entity- og relasjonsmodell
- Brønnøysundregistrene som primær norsk registerkilde
- Kildeproveniens, motsigelser og påstand-til-evidens-sporing

## Dokumentasjon

Se `docs/IMPLEMENTATION_PLAN.md` og dokumentene under `docs/` før implementasjon. `AGENTS.md` er autoritativ arbeidsinstruks for kodeagenter.

## Viktige begrensninger

Analysen skal ikke omgå innlogging, tilgangskontroll, betalingsmurer, CAPTCHA, robots-/rate-begrensninger eller andre tekniske sperrer. Systemet skal ikke bygge skjulte profiler eller trekke sensitive slutninger om helse, religion, etnisitet, seksuell orientering eller politiske meninger. Opplysninger om straffedommer/lovovertredelser krever særskilt juridisk vurdering og er ikke en standard datakilde.

## Lisens

Ingen åpen kildekode-lisens er valgt ennå. Opphavsrett beholdes inntil en lisens eksplisitt legges til.