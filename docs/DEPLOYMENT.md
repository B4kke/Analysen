# Lokal drift og oppstart

Analysen kjører som et monorepo på WSL2/Linux med Docker Compose. NVIDIA NIM er en valgfri hosted provider; grunnmuren starter uten API-nøkkel og uten GPU.

## Docker Compose

```bash
# Valgfritt: konfigurer NIM, porter og lokal SearXNG-secret.
cp .env.example .env
# Bruk en egen tilfeldig SEARXNG_SECRET dersom andre får tilgang.
docker compose up --build -d
docker compose ps
curl --fail http://localhost:8000/ready
```

Web: http://localhost:3000. API/OpenAPI: http://localhost:8000/docs. SearXNG: http://localhost:8080. Porter er bundet til loopback. PostgreSQL og Redis publiseres lokalt for utvikling. Denne leveransen er for én lokal operatør; autentisering, autorisasjon og retention må leveres før ekstern/flerbrukerdrift.

Oppstartsrekkefølge: PostgreSQL healthcheck → `migrate` → API/worker. Redis må være frisk før API/worker. Web venter på API. SearXNG er en separat discovery-tjeneste. `migrate` som avsluttes med exit 0 er normalt. `/health` er liveness; `/ready` krever både gjeldende databaseskjema og Redis.

API-/web-porter kan overstyres med `API_PORT` og `WEB_PORT`. `NEXT_PUBLIC_API_URL` bygges inn i web-bundelen; bygg web på nytt etter adresseendring. Ved endret web-port må `CORS_ORIGINS` også inneholde web-opprinnelsen. Se `.env.example`.

```bash
docker compose logs --tail=100 api worker migrate
docker compose stop
# Fjerner containere, beholder databasevolum:
docker compose down
```

Ikke bruk `down -v` for en installasjon med data som skal beholdes.

## Backup og restore

To datakilder sikkerhetskopieres separat: PostgreSQL (`postgres_data`) og raw evidence (`app_data`). Verifisert roundtrip 2026-09-17: dump, restore til scratch-database og identiske radtellinger.

```bash
# Database: dump til fil (kjør fra repo-roten, tilpass prosjektnavn ved behov).
docker compose exec -T postgres pg_dump -U analysen --format=plain --no-owner analysen > analysen-$(date +%F).sql

# Restore-verifisering til scratch-database før en eventuell reell restore:
docker compose exec -T postgres psql -U analysen -d postgres -c 'CREATE DATABASE analysen_restore_probe;'
docker compose exec -T postgres psql -U analysen -d analysen_restore_probe -q -f - < analysen-DATO.sql
docker compose exec -T postgres psql -U analysen -d analysen_restore_probe -tAc \
  "SELECT count(*) FROM investigations; SELECT count(*) FROM audit_log; SELECT version_num FROM alembic_version;"
# Sammenlign med live database, deretter:
docker compose exec -T postgres psql -U analysen -d postgres -c 'DROP DATABASE analysen_restore_probe;'

# Raw evidence (hash-adresserte snapshots i app_data-volumet):
docker run --rm -v analysen_app_data:/data -v "$PWD":/backup alpine \
  tar -czf /backup/app-data-DATO.tgz -C /data .
```

Reell restore av databasen: stopp api/worker, dropp og gjenskap databasen, last inn dumpen, kjør `alembic upgrade head` for sikkerhets skyld, start tjenestene og kontroller `/ready`. Raw snapshots gjenopprettes ved å pakke ut arkivet til et tomt `app_data`-volum før oppstart — innholdet er innholdsadressert, så duplikater er ufarlige. Ta backup før alle migreringer; fremoverrettede migreringer kan ikke rulles tilbake uten backup.

Compose bruker navngitte volumer for PostgreSQL (`postgres_data`) og felles API-/worker-data (`app_data`). SearXNG-konfigurasjonen bygges inn via `docker/searxng.Dockerfile`; endringer i `config/searxng/settings.yml` krever nytt bygg. Oppstart krever derfor ingen host bind-mounts og fungerer også med Windows Docker CLI fra WSL uten distro-mount-integrasjon.

**Eksisterende data:** Tidligere Compose brukte `./data:/app/data`. Innhold i `./data` blir ikke automatisk flyttet til `app_data`. Behold originalen, ta backup og kopier/verifiser innholdet i volumet før gammel lagring tas ut av bruk. PostgreSQL-volumet er uendret.

Ved Windows Docker CLI fra WSL kan shell-variabler mangle i Windows-prosessen. Legg portoverstyringer i en fil og bruk `docker compose --env-file <fil> up --build -d --wait`. Standard CORS-opprinnelser følger `WEB_PORT`; eksplisitt `CORS_ORIGINS` overstyrer dem. Web må bygges med samme env-fil slik at riktig API-port bygges inn.

## Mobiltilgang på samme nett

Web og API kan eksponeres på maskinens LAN-adresse slik at mobil på samme nett når samme UI. **Kun på klarert hjemmenett: det finnes ingen auth (ADR-017), så alle på nettet får tilgang.** Eksponer aldri mot internett.

```bash
# Finn maskinens LAN-adresse, f.eks. 192.168.1.10.
hostname -I
```

Legg i `.env` (eksempel med 192.168.1.10, web på 3000, API på 8000):

```bash
BIND_ADDRESS=0.0.0.0
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://192.168.1.10:3000
```

Postgres, Redis og SearXNG forblir på loopback — kun nettleserflatene (web/API) bindes på LAN. `CORS_ORIGINS` godtar kun loopback og RFC1918-adresser; offentlige verter avvises ved oppstart.

**Viktig:** `NEXT_PUBLIC_API_URL` bakes inn i web-bundelen ved bygg. Bygg web på nytt med LAN-adressen til API-et før mobilen kan bruke siden — og bruk deretter vanlig `up` (uten `--build`, som ville bygget web på nytt uten adressen):

```bash
docker compose build --build-arg NEXT_PUBLIC_API_URL=http://192.168.1.10:8000 web
docker compose up -d --wait
```

Åpne deretter `http://192.168.1.10:3000` på mobilen. Standard (uten `BIND_ADDRESS`) er fortsatt kun loopback.

### Windows-brannmur

Windows blokkerer innkommende trafikk som standard, også til publiserte Docker-porter. Dersom mobilen ikke får kontakt selv om alt svarer lokalt, mangler en tillatelsesregel. Kjør én gang i **administrator-PowerShell** (kun klarerte, private nett):

```powershell
New-NetFirewallRule -DisplayName "Analysen LAN" -Direction Inbound `
  -Protocol TCP -LocalPort 3000,8000 -Action Allow -Profile Private
```

Regelen åpner kun port 3000/8000 og kun på private nettverksprofiler. Verifiser fra Windows med `Test-NetConnection -ComputerName <LAN-IP> -Port 3000` — `TcpTestSucceeded` skal være `True` før mobilen testes.

### Dersom Docker ikke eksponerer porter på Windows

Hvis publiserte porter svarer fra WSL men ikke fra Windows (`Test-NetConnection` feiler) selv med brannmurregel, er Docker Desktops vertsvideresending ødelagt (restart av Docker Desktop hjelper vanligvis). Alternativet er å kjøre API/web nativt i WSL på `0.0.0.0` mot databasetjenestene i Docker:

```bash
DATABASE_URL=postgresql+asyncpg://analysen:analysen@localhost:5432/analysen \
REDIS_URL=redis://localhost:6379/0 \
CORS_ORIGINS=http://<LAN-IP>:3000,http://localhost:3000 \
nohup .venv/bin/uvicorn apps.api.app.main:app --host 0.0.0.0 --port 8000 &
NEXT_PUBLIC_API_URL=http://<LAN-IP>:8000 npm --prefix apps/web run build
nohup npm --prefix apps/web run start -- -H 0.0.0.0 -p 3000 &
```

Stopp da web/api-containerne først (`docker compose stop web api`) for å unngå portkonflikt. Native prosesser overlever ikke omstart — start dem på nytt etter reboot. Uvicorn uten `--reload` og Next-standalone laster kode ved oppstart: **restart begge etter kodeendringer**, ellers server de gammel kode (nye API-ruter gir 404 til nettleseren viser «Not Found»).

## Lokal Python og Node

Python 3.12 og Node 22+ er forutsetninger. Installasjon fra låste avhengigheter:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock
cd apps/web
npm ci
cd ../..
docker compose up -d postgres redis
alembic upgrade head
make dev-api
# I separate terminaler med samme miljø:
make worker
make web
```

På WSL uten `ensurepip`: installer distribusjonens `python3-venv`, eller bruk `uv venv .venv` og `uv pip sync requirements-dev.lock`. Kjør kommandoene fra repo-roten. `.env` er valgfri; lokale defaultverdier matcher Compose.

`requirements.lock` er runtime, `requirements-dev.lock` legger til utviklingsverktøy. Dokument-/crawlerpakken er flyttet til `requirements-research.lock` og installeres ved arbeid med disse modulene. Ingen eksisterende research-kode er fjernet. `make lock` regenererer låsene med uv; gjennomgå versjonsendringene før de tas i bruk.

## Databasemigreringer

Alembic er eneste migreringsmekanisme. `db/migrations/sql/0001_baseline.sql` er et frosset snapshot av det opprinnelige skjemaet. `0002_scope` legger til scope, modulstatus, entity expansion-state, leads og søkemetadata. `db/schema.sql` er et lesbart referanseskjema og brukes ikke som init-hook i Compose.

```bash
alembic current
alembic upgrade head
```

En eksisterende database fra repoets opprinnelige `schema.sql` kan oppgraderes direkte: baseline bruker `IF NOT EXISTS`. Ta backup først. Eksisterende investigations beholder data, får tomt research-scope, `CONTEXT_ONLY`, dybde 0 og en `SCOPE_MIGRATED` audit-hendelse. Velg scope eksplisitt før videre innhenting. Ikke bruk `stamp head` for å hoppe over schema-endringer.

Migreringene er fremoverrettede. Automatisk downgrade som fjerner scope-/auditdata er deaktivert; rollback skjer ved gjenoppretting av backup med tilhørende kodeversjon. Gjentatt `upgrade head` er trygt.

## Produksjon senere

Auth/RBAC, reverse proxy/TLS, administrerte secrets, backup/restore-øvelse, retention/deletion/export, egress-kontroll og overvåking er egne leveranser før ekstern drift. NIM-inferens testes separat med operatørens nøkkel; normal test-suite bruker ikke eksterne datakilder eller betalte modellkall.

Implementasjonen følger [Alembics async-oppsett](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic) og [Compose healthcheck-avhengigheter](https://docs.docker.com/compose/how-tos/startup-order/). SearXNG aktiverer [JSON-format eksplisitt](https://docs.searxng.org/admin/settings/settings_search.html).
