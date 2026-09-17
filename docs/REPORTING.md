# Rapportering

## Pipeline
Verified claim store + module coverage -> Report JSON -> HTML -> PDF. Ikke generer PDF direkte fra fri LLM-prosa.

## Dynamisk seksjonsmodell
Rapporten skal følge valgt investigation scope. Ikke-valgte moduler skal ikke late som de er undersøkt.

Mulige seksjoner:
1. Sammendrag
2. Mål og identitetsgrunnlag
3. Virksomhetsroller
4. Selskaps-/relasjonsnettverk
5. Økonomisk historikk
6. Tidslinje
7. Domene/web/media
8. Historisk web
9. Kunngjøringer/status
10. Sanksjonskontroll
11. Dokumenterte vesentlige funn
12. Motstridende opplysninger
13. Uavklarte spor
14. Metode og søkeomfang
15. Kilder/evidence

Bare relevante/aktiverte moduler får full seksjon. Identitetsgrunnlag, metode/søkeomfang og kilder/evidence er alltid med.

## Module status i rapporten
Metode/søkeomfang skal vise per modul:
- `UNDERSØKT`
- `UNDERSØKT_MED_GAPS`
- `IKKE_UNDERSØKT`
- `BLOKKERT_UTILGJENGELIG`

Vis expansion policy, max relation depth, kilder/providers forsøkt, relevant tidsrom, stop reason og vesentlige gaps.

Fravær av informasjon i en deaktivert eller ufullstendig modul er ikke et negativt funn.

## Finding states
- Confirmed/supported
- Partially supported
- Contradicted
- Insufficient evidence
- Unverified lead

Unverified leads skal visuelt og språklig skilles fra dokumenterte funn.

## Relaterte entities
Rapporten skal skille mellom:
- mål/entity som faktisk er undersøkt,
- `MATERIAL` relasjon som er undersøkt,
- `CONTEXT_ONLY` entity som kun er vist for kontekst.

Ikke presenter context-only entities som om det er utført full bakgrunnssjekk av dem.

## Citation UX
Klikkbar citation åpner source, retrieval timestamp, supporting excerpt/field, snapshot hash og eventuelt side/JSONPath.

## Negative evidence
Bruk formuleringer som beskriver faktisk coverage, f.eks. «Ingen relevante funn i de undersøkte åpne kildene innenfor oppgitt søkeomfang». Ikke skriv «finnes ikke» basert på manglende treff.

## Språk
Rapporter genereres på norsk som standard. Kildetekst kan beholdes på originalspråk med kort norsk parafrase.

## Ikke bruk
- person-risk score
- «sannsynligvis skyldig»/motivspekulasjon
- fravær av funn som bevis for fravær
- identitetskonklusjoner uten entity-resolution state
- rapportseksjon som impliserer at en modul ble undersøkt når den var deaktivert
