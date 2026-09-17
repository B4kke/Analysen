# BRREG role inventory — reverse index

## Hvorfor
Det åpne endepunktet `/api/roller/totalbestand` leverer zippet JSON for alle enheter og inkluderer fødselsdato. Det gjør det mulig å bygge lokal person->virksomhetsrolle candidate lookup uten å bruke fødselsnummer eller kommersielt API.

## Pipeline
1. Stream download til `data/ingest`.
2. SHA-256 hele arkivet + hentetid/source URL.
3. Valider ZIP og member sizes før extraction.
4. Stream parse JSON; ikke last alt i RAM.
5. Normaliser personnavn, behold original.
6. Parse fødselsdato og orgnr/role code.
7. Insert til staging table.
8. Dedupe og quality checks.
9. Bygg `(normalized_name, birth_date)` og orgnr-index.
10. Marker snapshot aktivt atomisk.

## Matching
Lookup returnerer candidates. Det er **ikke** en ferdig identitetskonklusjon. Hvis brukeren bare har navn, behold UNRESOLVED der navnebrødre finnes. Fødselsdato/år og kjente virksomheter styrker kandidatvalg.

## Inkrementell sync
Etter bootstrap: bruk BRREG rolleoppdaterings-endepunkt når semantics/checkpointing er implementert. Periodisk full snapshot beholdes som reconciliation.

## Personvern
Indexen inneholder åpne rolledata, men skal ikke eksponeres som et ubegrenset offentlig personsøk uten produkt-/personvernvurdering. Fødselsnummer-variant er ikke del av default pipeline.

## Referanse
https://data.brreg.no/enhetsregisteret/api/dokumentasjon/no/index.html
