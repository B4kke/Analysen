# Konkret implementasjonsplan

## Målbilde
En bruker oppretter en investigation med navn, eventuelt fødselsdato/år, sted og kjente virksomheter. Analysen identifiserer målpersonen, henter offisielle registerdata, bygger relasjonsgraf, finner nye spor, søker åpne nettsider, verifiserer koblinger og produserer en rapport der hver vesentlige påstand kan åpnes tilbake til kilden.

## Fase 0 — grunnmur
**Leveranser**
- monorepo-struktur
- Docker Compose
- FastAPI health/config
- PostgreSQL + pgvector
- Redis
- Next.js shell
- typed domain schemas
- NIM provider abstraction
- source adapter interface
- policy engine

**Exit:** `docker compose up` starter basistjenestene, API svarer health, database kan migreres, modell- og source-config valideres.

## Fase 1 — norsk registerkjerne
Implementer i denne rekkefølgen:
1. BRREG entity search/oppslag.
2. BRREG roller per orgnr.
3. BRREG åpen `roller/totalbestand` som periodisk bulkimport.
4. Lokal reverse-index: normalisert personnavn + fødselsdato -> roller/virksomheter.
5. BRREG juridiske roller for virksomhet -> andre virksomheter.
6. BRREG konsernstruktur.
7. Historiske navn/statusfelt.
8. Regnskapsregisteret: tilgjengelige år + PDF-kopi.

**Exit:** gitt en norsk person med nok identifikatorer kan systemet vise dokumenterte virksomhetsroller og relasjoner uten kommersiell tredjeparts-API.

## Fase 2 — evidence og entity resolution
- raw-document store med SHA-256
- `Source`, `Document`, `Evidence`, `Claim`, `ClaimEvidence`
- deterministic normalization
- candidate generation
- identity scoring med harde negative signaler
- `MATCH`, `PROBABLE_MATCH`, `UNRESOLVED`, `NOT_MATCH`
- manuell merge/split

**Exit:** samme navn alene kan ikke merge personer. Alle grafkanter har provenance.

## Fase 3 — web research
- SearXNG discovery
- URL canonicalization/dedup
- Trafilatura fast path
- Crawl4AI main path
- Playwright fallback
- SSRF/egress guard
- robots/rate/domain budgets
- Common Crawl/RDAP adapters
- søkehistorikk og query dedup

**Exit:** discovery-snippets kan aldri bli evidence; rapportering krever hentet originalkilde.

## Fase 4 — agentisk research-loop
- planner
- researcher/workhorse
- lead generator
- verifier
- contradiction detector
- frontier priority queue
- depth/budget/stop conditions
- checkpoint/resume

**Exit:** funn kan generere nye begrunnede leads, men ingen ubegrenset rekursjon.

## Fase 5 — dokument/regnskap
- PDF text/layout extraction
- tabelluttrekk
- OCR/multimodal fallback
- årsregnskapsnormalisering
- deterministiske finansnøkkeltall
- year-over-year-analyse
- noter/revisor/going-concern som claims med evidence

**Exit:** tall beregnes i kode, ikke av LLM.

## Fase 6 — rapport og UI
Fire hovedflater:
- Investigation: input, live events, budgets.
- Graph: personer/virksomheter/adresser/domener/dokumenter.
- Evidence: claims, støtte, motstrid, kildeviewer.
- Report: draft/reviewed/final.

Rapport: executive summary, identitetsgrunnlag, roller, virksomhetsnettverk, økonomi, tidslinje, web/media, material findings, contradictions, unresolved leads, metode og kilder.

## Fase 7 — kvalitet og sikkerhet
- norske gold fixtures
- source contract tests
- hallucination tests
- citation entailment tests
- false-positive entity-resolution suite
- prompt-injection suite
- SSRF suite
- privacy policy tests
- audit log

## Fase 8 — overvåking/endrede forhold
Kun etter stabil MVP:
- snapshot-to-snapshot diff
- nye roller/status/regnskap
- nye relevante åpne kilder
- endringsrapport

## Prioritert første sprint
1. Schema + config.
2. BRREG adapter.
3. Bulk role importer + reverse-index.
4. Person lookup API.
5. Evidence/provenance.
6. Entity resolution.
7. Enkel graph endpoint.
8. NIM extraction/verifier.
9. SearXNG + crawler.
10. Første kildebelagte HTML-rapport.

## Definition of done for MVP
- Norsk person kan identifiseres med eksplisitt usikkerhet.
- Offentlige virksomhetsroller kan reverssøkes fra lokal BRREG-indeks.
- Virksomheter, roller, konsern og årsregnskap kan hentes.
- Web discovery og crawling fungerer uten betalt search API.
- Alle material claims har evidence.
- Rapport skiller bekreftet, delvis støttet, motstridende og utilstrekkelig evidens.
- Ingen sensitiv inferens eller person-risikoscore.
