# Caching, dedup og ytelse

## Cache forslag
- BRREG entity/roles: 24 t, kortere ved aktiv monitoring.
- historiske årsregnskap: content-addressed/permanent snapshot; metadata kan refreshes.
- web page: 24 t–7 d etter type.
- RDAP/GLEIF: ca. 24 t.
- sanctions dataset: refresh daglig.
- search query: kort TTL + query hash for samme investigation.

## Dedup
- URL: canonical URL.
- dokument: SHA-256.
- query: normalized query hash.
- entities: conservative resolver, aldri bare dedup på navn.

## Concurrency
Global og per-domain semaphore. Offisielle API-er har separat limiter. Backoff med jitter ved 429/5xx.

## Large imports
BRREG roller-totalbestand skal stream-downloades og parses uten å laste hele datasettet i RAM. Import til staging, valider snapshot, bygg indekser og bytt aktiv snapshot transaksjonelt.

## Model routing
High-volume extraction går til Lightning; Super/Ultra brukes ved eskalering. Dette reduserer latency og gjør free endpoint-kvoter mer robuste.
