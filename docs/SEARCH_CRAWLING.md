# Search & crawling

## Discovery
Self-host SearXNG. Search providers er kun discovery og lagres som SearchResult. Query history dedupliseres.

## Fetch waterfall
1. `httpx` + Trafilatura for enkel HTML.
2. Crawl4AI for struktur/JS/deep crawl der tillatt.
3. Playwright kun når nødvendig.

## URL-policy
Kun http/https. DNS/IP kontrolleres før og etter redirect. Blokker localhost, RFC1918/private, link-local, metadata endpoints og `file://`.

## Domain policy
Per-domain concurrency, delay, max pages og failure backoff. Respekter eksplisitte tilgangsbegrensninger og ikke forsøk CAPTCHA/login bypass.

## Canonicalization
Fjern kjente tracking params, normaliser host/scheme/trailing slash forsiktig og behold original URL. Dedup med canonical URL + content hash.

## Historical web
Common Crawl er valgfri adapter for historiske snapshots. Historiske funn får egen valid-time og må ikke presenteres som nåværende fakta.

## RDAP
Bruk RDAP for offentlig domene-/registrarmetadata. Redigerte registrantdata skal forbli redigert; ingen forsøk på omgåelse.

## Search query generation
LLM kan generere queries rundt bekreftede identifiers/aliases. Queries som søker sensitive egenskaper eller private data blokkeres av policy engine.
