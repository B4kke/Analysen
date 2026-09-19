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
1. Kontrollert `httpx` henter og lagrer originale responsbytes før ekstraksjon.
2. Trafilatura og Crawl4AIs markdown-generator ekstraherer det lagrede HTML-innholdet uten egen nettverkstilgang.
3. Playwright brukes ved nødvendig JavaScript-rendering. Chromium er offline; dokumenter, scripts og XHR går gjennom samme kontrollerte HTTP-fetch via route fulfillment. Service workers og WebSockets blokkeres. Renderet HTML lagres som avledet snapshot med separat hash; originalhash og hentetid beholdes.

Denne waterfall tillater ikke automatisk deep crawl. Hver ekstra ressurs belastes samme request-/domenegrenser.

Deep crawl skal fortsatt være bundet til scope, information need og domain/page budget.

## URL-policy
Kun http/https uten innebygde credentials. Hvert redirect-hop valideres på nytt. HTTP-transporten resolver DNS og kobler direkte til en kontrollert offentlig IP med opprinnelig Host/TLS-SNI; proxy fra miljøet brukes ikke. Ikke-offentlige, multicast og private/mapped adresser avvises, inkludert localhost, link-local og metadata endpoints.

## Domain policy
Robots sjekkes før hvert nytt domene/hop. Robots 404 gir eksplisitt fravær; tilgangsfeil og utilgjengelig robots gir fail-closed. Per-domene concurrency gjelder hele respons-streamen, og requests har delay, sidebudsjett og en samlet request-grense per fetcher. Redirects er begrenset til tre. Wire- og dekomprimert innhold kontrolleres mot størrelsesgrensen under lesing. Respekter eksplisitte tilgangsbegrensninger og ikke forsøk CAPTCHA/login bypass.

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