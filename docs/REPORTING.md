# Rapportering

## Pipeline
Verified claim store -> Report JSON -> HTML -> PDF. Ikke generer PDF direkte fra fri LLM-prosa.

## Seksjoner
1. Sammendrag
2. Mål og identitetsgrunnlag
3. Virksomhetsroller
4. Selskaps-/relasjonsnettverk
5. Økonomisk historikk
6. Tidslinje
7. Domene/web/media
8. Dokumenterte vesentlige funn
9. Motstridende opplysninger
10. Uavklarte spor
11. Metode og søkeomfang
12. Kilder/evidence

## Finding states
- Confirmed/supported
- Partially supported
- Contradicted
- Insufficient evidence
- Unverified lead

Unverified leads skal visuelt og språklig skilles fra dokumenterte funn.

## Citation UX
Klikkbar citation åpner source, retrieval timestamp, supporting excerpt/field, snapshot hash og eventuelt side/JSONPath.

## Språk
Rapporter genereres på norsk som standard. Kildetekst kan beholdes på originalspråk med kort norsk parafrase.

## Ikke bruk
- person-risk score
- «sannsynligvis skyldig»/motivspekulasjon
- fravær av funn som bevis for fravær
- identitetskonklusjoner uten entity-resolution state
