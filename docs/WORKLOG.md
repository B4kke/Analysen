# Worklog

Kort, append-only oversikt over fullførte milepæler. Dette er ikke en ny TODO-liste; aktive oppgaver hører hjemme i `TASK_QUEUE.md`.

## 2026-09-17
- Etablert scope-first investigation design i `INVESTIGATION_SCOPE.md`: valgfrie research-moduler, expansion policy, materialitet og relation depth.
- Etablert trigger-driven research design i `SEARCH_TRIGGERS.md`: søketriggere, query classes, source routing, verifier-retry, stop rules og coverage ledger.
- Opprettet canonical AI-agent task queue med eksplisitt `READY/IN_PROGRESS/BLOCKED/DONE/CANCELLED`-flyt og definition of done.
- Synkronisert canonical docs, README og AGENTS med scope-first/trigger-driven design; AQ-003 lukket som `DONE`.
- Hentet Codex-arbeidskopien til `/home/b4kke/projects/Analysen` uten å endre originalen og pushet overtakelsespunkt `6f18fbb` til `codex/analysen-foundation` på GitHub.
- Rettet JSON-dekoding av audit-payload i migreringstesten og tilhørende lint. Verifisert Ruff, mypy (49 kildefiler), 48 tester med PostgreSQL-integrasjon, `npm run typecheck` og `npm run build`. AQ-008 er ikke ferdig: full Compose-/worker-/nettlesersmoke gjenstår.
- Docker-bygg for API, worker, migrate og web passerte. Isolert Compose-oppstart på alternative porter stoppet før full tjenestestart fordi Docker Desktop/WSL mangler distro-mount-socketen `ubuntu-24-04.sock`. AQ-008 satt `BLOCKED`; eksisterende Codex-miljø er ikke endret.
- Løst Compose-blokkeringen med SearXNG-konfigurasjon i image og navngitt appvolum; CORS-standard følger web-porten. Dokumentert eksisterende datamigrering og Windows CLI/env-fil. Rettet uvalgte modulers visning. AQ-008 lukket etter full Compose-oppstart, gjentatt migrering, worker-oppstart, 48 tester i Compose-nettverket, Ruff/mypy/TypeScript, Docker-webbygg og to beståtte Chromium-smoker for opprettelse, detalj, reload og scope. Ingen live research eller bulkimport kjørt.
- AQ-004 lukket: regresjonssuite for scope-innsnevring (`tests/integration/test_scope_narrowing.py`) verifiserer blokkering av ventende leads utenfor scope, bevart coverage/status ved innsnevring og full rollback når audit ikke kan lagres. 50 tester passerer i Compose-nettverket; Ruff og mypy rene.
