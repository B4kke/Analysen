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

## BRREG reverse-index
Importer åpen `roller/totalbestand` med fødselsdato. Indekser normalisert navn + fødselsdato og behold orgnr/rolletype/source snapshot. Ikke importer fødselsnummer-varianten uten berettiget tilgang.

## Testing
Gold set må inneholde navnebrødre, navneendringer, mellomnavn, norske tegn, identiske navn i samme kommune og historiske roller.
