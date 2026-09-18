# Nasjonalbiblioteket — canonical source contract

Dette dokumentet er autoritativt for integrasjon av Nasjonalbiblioteket (NB), DH-lab og IIIF i Analysen.

Målet er ikke å rapportere at et navn «finnes i en avis». Målet er å hente den rikeste lovlig tilgjengelige konteksten, bevare provenance og tilgangsstatus, avklare identitet og presentere faktisk innhold i rapporten.

## Scope

NB brukes primært under `WEB_MEDIA` og ved eksplisitte historiske behov under `HISTORICAL_WEB`.

En direkte NB-lookup på investigation-target er tillatt når relevant scope er aktivt. En avisforekomst av en ny person eller organisasjon gir aldri automatisk autorisasjon til å undersøke den entityen videre.

## Offisielle tjenester

### Catalog API

Base:
`https://api.nb.no/catalog/v1`

Bruk:
- metadata- og OCR-fulltekstsøk,
- resultatantall og aggregasjoner,
- item metadata,
- access metadata,
- side-lokalisering via content fragments,
- metadata/structure/IIIF-resolvering.

For avisresearch brukes `searchType=FULL_TEXT_SEARCH`.

### Catalog content fragments

`/items/{item_id}/contentfragments`

Brukes som page locator, ikke som primær article-text-provider.

Live-prober 2026-09-18 viste at selv store `fragSize`-verdier kunne returnere bare:

`... <em>Maylen Sorkness Andersen</em> ...`

Implementasjonen må derfor aldri anta at dette endepunktet gir artikkeltekst.

### IIIF Content Search

`/contentsearch/{item_id}/search?q=...`

Returnerer OCR-token og målkoordinater, typisk `xywh=x,y,w,h`, bundet til konkret canvas/page URN.

Dette brukes som tekstanker for:
- eksakt sidetreff,
- article-region extraction når sidebildet lovlig kan behandles,
- presis evidence-locator.

### Metadata / structure / manifest

Brukes for:
- issue-/page-URN,
- siderekkefølge,
- sidebredde/-høyde,
- scan resolution,
- identifikatorer,
- publikasjon/dato,
- eventuelle image services,
- rights/access metadata.

Ikke anta at avisobjektet har ferdig artikkelsegmentering. I live-testene bestod structure i hovedsak av sidene og deres ressurser/geometri.

### DH-lab

Base:
`https://api.nb.no/dhlab`

Viktigste første endepunkt:
`POST /conc`

Input skal minst inneholde:
- URN-er,
- query,
- bounded window,
- bounded limit.

DH-lab-konkordans er primær kilde til keyword-in-context når Catalog bare lokaliserer treffet.

Kontekst fra `/conc` er `PARTIAL_CONTEXT`, aldri automatisk `FULL` article text.

Andre DH-lab-operasjoner kan brukes målrettet når informasjonsbehov tilsier det, blant annet:
- collocations,
- concordance counts,
- places,
- dispersion,
- frequencies/ngrams,
- metadata/identifiers.

Disse er analysehjelp, ikke selvstendige bevis på identitet.

## Live referanser fra 2026-09-18

### Maylen Sorkness Andersen

Eksakt OCR-fulltekstsøk i aviser gav 10 issue candidates:
- Aftenposten — 1994-12-16 — side 72
- Akers Avis Groruddalen — 2001-08-29 — side 12
- Hadeland — 2005-12-13 — side 17
- Hadeland — 2007-08-06 — side 23
- Hadeland — 2007-08-27 — side 27
- Hadeland — 2007-10-05 — side 35
- Hadeland — 2008-02-29 — side 17
- Hadeland — 2020-12-23 — side 25
- Hadeland — 2025-12-19 — side 29
- Romerikes Blad — 2026-05-19 — side 30

Disse er discovery-/mention-candidates. De er ikke automatisk samme person som investigation-target.

På Romerikes Blad 2026-05-19 returnerte IIIF Content Search eksakte OCR-koordinater for Maylen/Sorkness/Andersen på side 30. Materialet var samtidig tilgangsbegrenset. Dette er referansecaset for «locator tilgjengelig, sideinnhold ikke fritt kopierbart».

Flere åpne Hadeland-treff demonstrerte at sidebildet kan være tilgjengelig selv om separat full-OCR-endepunkt ikke nødvendigvis returnerer fri fulltekst. `viewability` og «kan lagres/republiseres» må derfor behandles som forskjellige spørsmål.

### Eltonåsen

Eksakt avissøk på `Eltonåsen` gav tusenvis av issue candidates.

Dette er canonical stress-case for:
- pagination,
- result caps,
- query refinement,
- dedup,
- coverage,
- stop rules.

Systemet skal aldri forsøke å hente alle sider fra et slikt stedsøk.

## Desired vertical pipeline

```text
target / verified alias
  -> deterministic nb_newspaper_search lead
  -> Catalog FULL_TEXT_SEARCH
  -> immutable raw Catalog snapshot
  -> issue candidates
  -> access/rights normalization
  -> contentfragments page locator
  -> IIIF Content Search xywh
  -> DH-lab /conc
  -> MediaMentionCandidate
  -> entity resolution
  -> rights gate
       -> restricted: context + metadata + NB link
       -> permitted: page image -> anchored article segmentation -> OCR/crop
  -> typed extraction
  -> Evidence / ClaimCandidate
  -> verifier
  -> ReportDocument.media_mentions
  -> JSON / HTML / PDF / web
```

## Lead and trigger contract

Ny allowlisted lead type:
`nb_newspaper_search`

Initial lookup for an explicit person target must be deterministic when `WEB_MEDIA` is selected; it skal ikke avhenge av at planner «oppdager» NB.

Bruk en eksplisitt target-level/direct-source trigger, for eksempel `DIRECT_SOURCE_LOOKUP`. Ikke misbruk `WEAK_SOURCE_ONLY` eller en passiv `MEDIA_CORROBORATION`-trigger som initial seed.

Verified aliases may create additional deduplicated exact-name NB leads.

## Required typed models

Implementasjonen skal ha typed contracts tilsvarende:

### NBSearchCandidate
- item_id
- publication
- issued_at
- issue_urn
- access metadata
- rank/result position

### NBPageHit
- item_id
- issue_urn
- page_urn
- page_number
- query
- text anchors / xywh
- thumbnail when provided

### NBAccessDecision
- normalized state
- original upstream access fields
- allow_metadata
- allow_context
- allow_full_text_storage
- allow_page_fetch
- allow_derived_crop
- allow_report_embed
- reason

### MediaMentionCandidate
- target/query
- publication
- published_at
- page number
- issue/page URN
- text availability
- context excerpt
- headline/body/caption if actually extracted
- identity state
- access/license metadata
- source URL
- evidence/document references

## Item-level rights and access

NB er en mixed-rights source. Source-level `PUBLIC_WEB` er ikke nok til å bestemme hva et enkelt avisobjekt kan brukes til.

Persistér upstream fields when present, including:
- `accessAllowedFrom`,
- `viewability`,
- `isPublicDomain`,
- license/license code,
- rights URI,
- attribution,
- original access metadata.

Normaliser til konservative typed states, for eksempel:
- `PUBLIC_REUSE`
- `PUBLIC_VIEW_ONLY`
- `LIBRARY_ONLY`
- `NB_ONLY`
- `UNKNOWN`

Policy must fail closed. Ukjent/ufullstendig rights metadata skal aldri oppgraderes til «kan embeddes».

`viewability=ALL` betyr ikke automatisk at full side eller crop fritt kan republiseres.

Ingen bypass av innlogging, bibliotektilgang, token, betalingsmur, CAPTCHA eller andre tilgangskontroller.

## Text availability

Hver media mention skal deklarere:
- `FULL`
- `PARTIAL_CONTEXT`
- `UNAVAILABLE`

`FULL` krever at full artikkeltekst faktisk er lovlig tilgjengelig og hentet.

`PARTIAL_CONTEXT` brukes for DH-lab-concordance eller annet begrenset lawful context.

`UNAVAILABLE` brukes når systemet bare kan dokumentere treff/side/metadata/link.

Rapport/UI må aldri kalle en concordance «full artikkeltekst».

## Permitted page/image extraction

Kun når item-level policy eksplisitt tillater behandling:

1. hent original side/image bytes,
2. lagre immutable raw snapshot før avledet behandling,
3. bruk IIIF `xywh` som anchor,
4. bruk Pillow + pytesseract `image_to_data(lang="nor")` for word/line/block geometry,
5. finn OCR-regionen som inneholder target expression,
6. ekspander konservativt til sannsynlig artikkelregion,
7. valider at target fortsatt finnes i cropen,
8. lagre crop som eget immutable derived document,
9. OCR cropen på nytt,
10. lagre crop coordinates + parent page URN + hashes.

Vision-modellen er bare `DOCUMENT_QUALITY` fallback for layout/region-detection. Den skal ikke brukes som ansiktsidentifikasjon.

## Full article recovery priority

Foretrekk i denne rekkefølgen:
1. offentlig original nettartikkel gjennom eksisterende safe DocumentFetcher,
2. NB fulltext der upstream rights eksplisitt tillater det,
3. OCR fra rettighetsgodkjent avis-/article crop,
4. DH-lab partial context,
5. metadata + page locator + direkte NB-link.

Hvis NB/nettavis metadata gir original target URL, opprett et vanlig gated `web_document_fetch` lead. Search/discovery metadata alene er ikke evidence.

## Identity semantics

Et exact-name hit er `MediaMentionCandidate`, ikke target identity.

Navn alene kan aldri bli MATCH.

Bruk eksisterende entity-resolution-signaler:
- verifisert sted,
- virksomhet/organisasjon,
- tidslinje,
- fødselsår/dato der lovlig og nødvendig,
- verified aliases,
- andre dokumenterte relasjoner.

Ambiguity skal ende i `UNRESOLVED` når kildene ikke er sterke nok.

## Extraction semantics

Typed extractor output may include:
- headline,
- article_text,
- summary,
- target_context,
- persons,
- organizations,
- places,
- dates,
- roles,
- caption_text,
- claim_candidates.

LLM-output er forslag, aldri evidence. Claims må peke til concrete Evidence IDs og gå gjennom eksisterende verifier/citation gate.

## Provenance

Canonical chain:

`NB response/page -> raw snapshot -> Document -> Evidence -> Claim -> Verification -> Report citation`

Evidence locator for NB skal kunne bevare:
- item ID,
- issue URN,
- page URN,
- page number,
- query,
- concordance window,
- xywh,
- publication,
- issue date,
- upstream access/license fields.

Raw API-responses brukt til evidence lagres før parsing/normalisering.

## Report contract

Utvid `ReportDocument` med `media_mentions`.

Hver report media mention skal minst kunne inneholde:
- publication
- published_at
- page_number
- headline
- summary
- text_excerpt
- text_availability
- identity_state
- issue_urn
- page_urn
- source_url
- access_class
- license_code
- image_document_id
- image_embeddable
- citations

Når crop/fulltekst kan inkluderes lovlig, kan HTML/PDF vise den med kilde/attribution/hash.

Når innhold ikke kan inkluderes, vis metadata, lawful context og direkte NB-link med eksplisitt access forklaring.

JSON, HTML, PDF og Next.js må konsumere samme canonical report contract.

## Coverage

`WEB_MEDIA` coverage skal registrere:
- NB providers/endpoints forsøkt,
- query class,
- query count,
- candidate count,
- page-located count,
- concordance count,
- full-text count,
- restricted count,
- fetched page/crop count,
- unavailable/restricted sources,
- tidsrom,
- stop reason.

«Ingen funn» er bare gyldig innen dokumentert coverage.

## Budgets and stop rules

En NB-search må være bounded:
- max issues per query,
- max pages per issue,
- max page/image fetches,
- max concordances,
- dedup på item/page/query,
- stop ved gjentatte/dupliserte resultater,
- stop når identity forblir unresolved etter relevante signaler,
- stop når rights/access blokkerer videre lovlig innhenting,
- stop når information need er besvart.

## Required tests

CI skal ikke være avhengig av live NB.

Bruk sanitiserte fixtures basert på live response-shapes. Ikke commit beskyttet full artikkeltekst.

Minimum:
- exact-name Catalog response parsing,
- contentfragments behandles som locator, ikke full text,
- IIIF xywh parsing,
- DH-lab concordance -> `PARTIAL_CONTEXT`,
- access matrix fail-closed,
- restricted case never calls page-image downloader,
- permitted case: page -> crop -> OCR -> evidence,
- same-name hit remains UNRESOLVED without corroboration,
- report JSON/HTML/PDF exposes same media mention semantics,
- rerun idempotency,
- PostgreSQL migration from current head and fresh database.

Optional live contract probe:
`scripts/nb_probe.py`

Probe can use Maylen Sorkness Andersen and Eltonåsen to verify current endpoint shapes, but live results are diagnostics, not deterministic CI assertions.

## Files expected in implementation

Suggested new files:
- `apps/api/app/domain/nb_media.py`
- `apps/api/app/sources/national_library.py`
- `apps/api/app/services/nb_access_policy.py`
- `apps/api/app/services/nb_article_locator.py`
- `apps/api/app/services/nb_article_extract.py`
- `apps/api/app/services/executors/nb_media.py`
- `apps/api/app/repositories/media_mentions.py`
- `db/migrations/versions/0006_nb_media.py`
- `tests/fixtures/nb/`
- `tests/test_nb_access_policy.py`
- `tests/test_nb_adapter.py`
- `tests/test_nb_article_extract.py`
- `tests/integration/test_nb_media_pipeline.py`
- `scripts/nb_probe.py`

Existing integration points:
- `config/sources.yaml`
- `apps/api/app/core/config_models.py`
- `apps/api/app/domain/scope.py`
- `apps/api/app/services/source_router.py`
- `apps/api/app/services/lead_executor.py`
- `apps/api/app/services/research_loop.py`
- `apps/worker/app/tasks.py`
- `apps/api/app/domain/report.py`
- `apps/api/app/services/report_build.py`
- `apps/api/app/services/report_render.py`
- `apps/web/app/types.ts`
- `apps/web/app/investigations/[id]/report/page.tsx`

## Definition of done

NB-stacken er ikke ferdig før en kontrollert E2E-test beviser:

`person target -> deterministic NB seed -> lead gate -> source router -> NB adapter -> raw snapshot -> page/concordance -> rights gate -> MediaMention -> entity resolution -> evidence/claim -> verifier -> coverage -> ReportDocument -> JSON/HTML/PDF/web`

External NB/model boundary kan fakes i E2E. Database, repositories, research-loop, provenance, verifier og report builder skal være ekte.
