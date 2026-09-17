# Search & crawling

`SEARCH_TRIGGERS.md` er autoritativ for når et nytt søk er tillatt og hvilken query/source-strategi som skal brukes.

## Discovery
Self-host SearXNG. Search providers er discovery-lag og lagres som `SearchResult`. Query history dedupliseres.

Search er ikke default for alle behov. Source router skal først velge målrettet/offisiell adapter når en slik finnes.

## Query generation
Alle queries har `originating_lead_id`, `scope_area`, `query_class`, `intent` og `reason`.

LLM kan generere queries rundt bekreftede identifiers/aliases, men scheduler validerer:
- aktiv scope-modul,
- expansion policy,
- at query ikke er duplikat/repeated loop,
- at den ikke inneholder unødvendige persondata,
- at query ikke søker sensitive egenskaper/private data.

Full fødselsdato fra lokal/offisiell indeks brukes primært internt til entity resolution og skal ikke automatisk sendes til websearch.

## Source routing
Foretrekk direkte source adapter foran bred websearch:
- BRREG for enhet/roller/konsern,
- Regnskapsregisteret for årsregnskap,
- RDAP for domene metadata,
- Common Crawl for historisk kjent URL/domene,
- SearXNG/GDELT for bred omtale/discovery.

## Fetch waterfall
1. `httpx` + Trafilatura for enkel HTML.
2. Crawl4AI for struktur/JS/deep crawl der tillatt og nødvendig.
3. Playwright kun når nødvendig.

Deep crawl skal fortsatt være bundet til scope, information need og domain/page budget.

## URL-policy
Kun http/https. DNS/IP kontrolleres før og etter redirect. Blokker localhost, RFC1918/private, link-local, metadata endpoints og `file://`.

## Domain policy
Per-domain concurrency, delay, max pages og failure backoff. Respekter eksplisitte tilgangsbegrensninger og ikke forsøk CAPTCHA/login bypass.

## Canonicalization
Fjern kjente tracking params, normaliser host/scheme/trailing slash forsiktig og behold original URL. Dedup med canonical URL + content hash.

## Historical web
Common Crawl er adapter for historiske snapshots når `HISTORICAL_WEB` er aktiv eller en eksplisitt temporal/identity trigger krever historisk kontekst. Historiske funn får egen valid-time og må ikke presenteres som nåværende fakta.

Ikke kjør vilkårlige historiske søk på alle entities.

## RDAP
Bruk RDAP for offentlig domene-/registrarmetadata når domene er relevant og scope tillater det. Redigerte registrantdata skal forbli redigert; ingen forsøk på omgåelse.

## Evidence
SearXNG/GDELT snippets er discovery only. Originalsiden/dokumentet må hentes før en claim kan støttes.

## Coverage
Per aktiv modul lagres:
- providers forsøkt,
- query classes,
- antall queries/results/fetched/relevant,
- tidsrom der relevant,
- utilgjengelige kilder,
- stop reason,
- åpne gaps.

Coverage brukes både av planner og rapportgenerator.