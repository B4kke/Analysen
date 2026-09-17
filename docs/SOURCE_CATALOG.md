# Source catalog

Hver kilde implementeres som adapter med metadata: `id`, `authority`, `access`, `license`, `person_data`, `company_data`, `historical`, `default_enabled`, `rate_policy`, `evidence_tier`.

## Første bølge
| Kilde | Formål | Tilgang | Tier |
|---|---|---|---|
| BRREG Enhetsregister | virksomhet/status/adresse/navn | åpen | 1 |
| BRREG roller | roller per virksomhet | åpen | 1 |
| BRREG rolle-totalbestand | lokal person->rolle reverse-index | åpen | 1 |
| BRREG konsernstruktur | selskapsgruppe | åpen | 1 |
| Regnskapsregisteret | årsregnskap PDF | åpen | 1 |
| BRREG kunngjøringer | konkurs/tvang/oppløsning | offentlig web | 1 |
| SearXNG | discovery | self-hosted | discovery |
| Original webside | web evidence | offentlig web | 2-5 |
| Common Crawl | historiske websider | åpen | 3-5 |
| RDAP | domene metadata | åpen/federert | 2 |
| GLEIF | internasjonale juridiske enheter/LEI | åpen | 1 |
| EU Financial Sanctions | offisiell sanksjonsliste | åpen | 1 |
| GDELT | news discovery | åpen | discovery/3 |

## Senere/valgfritt
- OpenSanctions/yente: entity matching/screening; datasettlisens må vurderes for brukstilfellet.
- ICIJ Datashare: dokumentarkitektur/inspirasjon eller separat importflyt.
- Maigret: kun når et kjent offentlig brukernavn allerede er relevant; treff er kandidater, ikke identitetsbevis.
- passive Amass/subfinder/theHarvester: kun virksomhetsdomener og passive moduler, ikke aktiv sikkerhetsskanning.

## Tilgangsklasser
- `OPEN_NO_KEY`
- `OPEN_FREE_KEY`
- `ENTITLEMENT_REQUIRED`
- `DISABLED_BY_POLICY`
- `PAID_OPTIONAL`

## Evidence-tier
Tier 1: offisielt register/myndighet/primærdokument.
Tier 2: virksomhetens offisielle dokument/nettside.
Tier 3: etablert redaksjonelt medium/fagkilde.
Tier 4: bransjekatalog/aggregering.
Tier 5: brukerpublisert/offentlig sosial profil/forum.

Kildetier påvirker hvor mye corroboration som kreves, men «authority score» skal aldri erstatte konkret evidens.
