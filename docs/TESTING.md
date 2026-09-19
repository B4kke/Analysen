# Testing og evaluering

## Unit
Normalization, URL canonicalization, financial formulas, policy, confidence components, scope gates, expansion policy og trigger selection.

## Source contract
Recordede offentlige fixtures for BRREG schema og regnskapsmetadata. Live smoke tests separat og rate-begrenset.

## Entity resolution gold set
Navnebrødre, ulike fødselsdatoer, navnevarianter, samme kommune, historiske roller, virksomhetsbytter. Hovedmål: svært lav false-positive merge rate.

Test også at identity resolution ikke åpner full research av relaterte entities uten aktivt scope.

## Scope-gate tests
Obligatoriske cases:
- deaktivert modul kan aldri planlegges/kalles,
- globalt enabled source er ikke nok uten aktivt scope,
- `CONTEXT_ONLY` entity auto-ekspanderes ikke,
- `DIRECT_RELATIONS` respekterer relation depth,
- `MATERIAL_RELATIONS` krever eksplisitt material reason/information need,
- scope-utvidelse åpner relevante leads og auditeres,
- scope-innsnevring stopper nye actions.

## Search-trigger evals
Obligatoriske cases:
- `IDENTITY_AMBIGUITY` velger målrettet resolution fremfor bred research,
- `WEAK_SOURCE_ONLY` søker sterkere/uavhengig kilde,
- `CONTRADICTION` lager disconfirmation lead,
- `TEMPORAL_GAP` velger tids-/historikkilder,
- `DOCUMENT_QUALITY` prøver parser/OCR/VLM før irrelevant websearch,
- `FINANCIAL_ANOMALY` trigges bare når FINANCIALS er aktiv og entity er target/material,
- repeated query/result loop stopper,
- ingen nye high-value leads gir stop.

## LLM evals (norsk)
- structured extraction F1
- JSON/schema validity
- Norwegian names/letters
- tool-call validity
- scope/tool routing validity
- claim/evidence entailment
- contradiction detection
- refusal to guess when evidence missing
- prompt-injection resistance
- confirmation-bias/disconfirm behavior

## Hallucination test
Spør om attributt som ikke finnes i evidence. Forvent `INSUFFICIENT_EVIDENCE`, aldri gjetning.

## Citation gate
Hver material report claim må ha minst én evidence link; verifier skal kontrollere entailment før report state kan bli REVIEWED.

## Coverage/report tests
Rapportgenerator skal korrekt skille:
- undersøkt,
- undersøkt med gaps,
- ikke undersøkt,
- blokkert/utilgjengelig.

Ikke-valgt modul skal aldri omtales som «ingen funn».

## Security
SSRF, redirects, DNS rebinding, malicious HTML instructions, archive bombs, oversized docs og secrets redaction.

## Repo-hygiene gate
En oppgave skal ikke markeres `DONE` før relevante docs/tests er synkronisert. CI/lint kan senere kontrollere at kjente TODO/FIXME følger en task-ID eller eksplisitt policy.


## Kjørbare kontroller for grunnmuren

Installer `requirements-dev.lock` og `apps/web/package-lock.json` først.

```bash
ruff check .
mypy apps
pytest -q
# Ekte PostgreSQL, isolerte testdata (inkl. midlertidig migration-database):
# Start egen PostgreSQL/Redis for test; oppgi kun testdatabase.
DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head
TEST_DATABASE_URL="$TEST_DATABASE_URL" REDIS_URL="$TEST_REDIS_URL" pytest -q
cd apps/web
npm run typecheck
npm run build
```

Uten `TEST_DATABASE_URL` skippes databaseintegrasjon eksplisitt. CI setter variabelen og kjører testene mot pgvector/PostgreSQL 17. Bruk en egen utviklings-/testdatabase. Migreringstesten trenger CREATEDB-rettighet og rydder bare sin egen tilfeldig navngitte database.

Integrasjonssuiten verifiserer lagret scope, alle ni modulrader, before/after-audit, fail-closed BRREG-gate før upstream, positiv ingest med fixture og bevaring av innsamlede data ved innsnevring. Eksterne kildekall erstattes kun ved nettverksgrensen. Runtime-testene kontrollerer liveness, readiness 200/503 og CORS-preflight for PATCH.

Automatisert nettlesersmoke mot en lokal testinstans:

```bash
cd apps/web
npx playwright install chromium
TEST_WEB_URL=http://127.0.0.1:53010 TEST_API_URL=http://127.0.0.1:58010 npm run test:smoke
```

Bruk portene som instansen er bygget/startet med. Testen oppretter syntetiske saker gjennom web-skjemaet og rydder dem via API etterpå; kjør kun mot en isolert testdatabase og worker. Den kjører Chromium med ekte JavaScript og API, uten mocked research. På Docker Desktop/WSL kan direkte PostgreSQL-port være utilgjengelig fra lokal Python selv om web fungerer. Kjør da testene inne i Compose-nettverket, med `TEST_DATABASE_URL=postgresql+asyncpg://analysen:analysen@postgres:5432/analysen` og `CORS_ORIGINS=http://localhost:3000` (runtime-testens faste opprinnelse).

Nettlesersmoke: opprett en syntetisk investigation i web, åpne detaljsiden, last siden på nytt og kontroller at lagret navn/scope/moduler beholdes. Uvalgte områder skal vises som ikke valgt, aktive uutførte områder som ikke undersøkt. Ingen NIM-nøkkel eller live personresearch er nødvendig.


## Research-runtime og live state (AQ-021/AQ-025)

`docker/api.Dockerfile` installerer hele `requirements-research.lock`, Chromium, Java og Tesseract med norsk språk. Dev-lock alene er ikke tilstrekkelig for extractor/browser-kontrollen. Installer testverktøy bare i et separat testmiljø basert på samme runtime, og kjør:

```bash
pytest -q tests/test_research_runtime.py
TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest -q tests/integration/test_investigation_state.py
```

Runtime-fixtures bruker ekte Trafilatura, Crawl4AI og Playwright og kontrollerte HTTP-responser. Nettverket kan frakobles for disse fem testene; de skal passere uten skip i research-image. Det samme image har norsk OCR og PDF-avhengigheter. Integrasjonstesten bruker ekte PostgreSQL og kontrollerer korrelert job-ID, køfeil/retry, avvisning av duplikatstart, worker som fullfører før kø-audit, konsistent detaljsnapshot under samtidig worker-commit, kildeprovenance og vedlegg som mangler/er korrupte/tilhører en annen sak. Eksterne modell-/kildekall erstattes bare ved kildegrensen.

Nettlesertesten krever en faktisk Redis-worker på samme isolerte testdatabase. En ny sak uten leads fullfører en avgrenset pass uten nettverkskall. `TEST_POPULATED_ID` kan settes til en syntetisk sak som allerede har kjørt den virkelige ingest-/research-tjenesten med en ekstern kildefixture; da kontrolleres også entities, claims, kildebelegg og nedlasting av lagrede originalbytes. Siden kontrolleres ved 390 pikslers bredde. Nettlesertesten forutsetter web bygget med API-adressen som brukes i testen.


Verifisert 2026-09-18: 281 tester passerer uten skip i separat research-runtime med PostgreSQL 17/Redis. Ruff, mypy (67 kildefiler), TypeScript og Next.js-produksjonsbygg passerer. Chromium kontrollerer company/person/domain-skjema, mobilbredde, reload, rapport, stale-data/recovery, faktisk worker-fullføring og en syntetisk sak med lagret provenance. En egen kontroll med fem sekunders GET-latens og pauset/gjenopptatt isolert worker viser terminalstatus uten reload; automatiske polls venter på forrige svar. Ingen live personresearch eller modellkall inngår i denne runden.
