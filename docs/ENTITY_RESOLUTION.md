# Entity resolution

## Problem
Norske navn er ikke unike. Samme navn skal aldri være nok til å koble person til virksomhet eller nettside.

## Pipeline
1. Normaliser navn (Unicode, whitespace, rekkefølge uten å miste originalen).
2. Candidate generation fra BRREG reverse-index, kjente selskaper, fødselsdato/år og sted.
3. Feature extraction.
4. Deterministiske hard negatives.
5. Weighted evidence score/state.
6. LLM kan forklare tvetydighet, men kan ikke overstyre harde konflikter.
7. Auto-merge kun over konservativ threshold; ellers human review.

## Signaler
Sterke: eksakt fødselsdato, stabil unik virksomhetskobling, eksplisitt offisiell identifikasjon.
Middels: flere sammenfallende roller, tidslinje, offentlig profesjonell biografi, konsistente steder.
Svake: navn, arbeidstittel alene, samme kommune, sosial profil-likhet.
Hard negative: ulik fødselsdato, umulig tidslinje, eksplisitt annen person.

## States
- `MATCH`: sterk evidens og ingen hard contradiction.
- `PROBABLE_MATCH`: flere konsistente signaler, men mangler sterk identifikator.
- `UNRESOLVED`: utilstrekkelig/tvetydig.
- `NOT_MATCH`: hard motstrid.

## Identity-triggered research
Identitetsavklaring er alltid tillatt som minimal systemhygiene, men skal ikke brukes som bakdør til full research uten aktiv scope-modul.

`IDENTITY_AMBIGUITY` kan trigge målrettede lookups/søk etter:
- offisielle roller,
- kjent virksomhet,
- sted/tidslinje,
- historiske navn/alias,
- andre sterke/middels signaler.

Når nok relevante kilder er forsøkt skal systemet kunne stoppe i `UNRESOLVED`; det skal ikke grave ubegrenset for å tvinge frem en match.

## Relaterte entities
Ny person/virksomhet oppdaget under entity resolution blir som standard `CONTEXT_ONLY` med mindre den er nødvendig for selve identitetsavklaringen eller aktiv scope/expansion policy tillater videre research.

Samme adresse, samme kommune, navnelikhet, medieomtale sammen eller sosial profil-likhet skal aldri alene utløse automatisk ekspansjon.

## BRREG reverse-index
Importer åpen `roller/totalbestand` med fødselsdato. Indekser normalisert navn + fødselsdato og behold orgnr/rolletype/source snapshot. Ikke importer fødselsnummer-varianten uten berettiget tilgang.

Fødselsdato brukes primært internt til resolution. Ikke bygg queries som automatisk eksponerer full fødselsdato til offentlige søkemotorer.

## Testing
Gold set må inneholde navnebrødre, navneendringer, mellomnavn, norske tegn, identiske navn i samme kommune og historiske roller.

Mål:
- svært lav false-positive merge rate,
- korrekt `UNRESOLVED` når evidens mangler,
- ingen uautorisert scope-ekspansjon under identitetsavklaring.
