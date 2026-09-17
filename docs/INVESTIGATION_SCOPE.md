# Investigation scope

Dette dokumentet er autoritativt for **hva en investigation får lov til å undersøke**. Discovery er ikke autorisasjon til å utvide scope.

## Prinsipp
En bruker velger eksplisitt hvilke undersøkelsesområder som skal aktiveres. Planner, lead generator og source router kan bare foreslå handlinger innenfor aktivt scope, gjeldende policy og budsjetter.

**Invariant:** En nyoppdaget entity kan lagres som kontekst, men kan bare undersøkes videre når:
1. relevant scope-modul er aktivert,
2. relasjonen tilfredsstiller expansion policy,
3. det finnes et konkret informasjonsbehov,
4. handlingen er innen policy og budsjett.

## Alltid aktivt: identitetsavklaring
Identitetsavklaring er systemhygiene, ikke en valgbar research-modul. Systemet må avklare at kilder og funn gjelder riktig målperson/-virksomhet før de brukes som grunnlag for claims.

Identitetsavklaring kan bruke minimalt nødvendige offisielle identifikatorer og kontekstsignaler, men skal ikke åpne full bakgrunnssjekk av relaterte personer eller selskaper.

## Scope-moduler
Følgende moduler kan velges per investigation:

- `WEB_MEDIA`: offentlig web, medier og fagkilder.
- `BUSINESS_ROLES`: dokumenterte virksomhetsroller og grunnleggende virksomhetskontekst.
- `COMPANY_NETWORK`: konsern, juridiske roller og vesentlige selskapsrelasjoner.
- `FINANCIALS`: årsregnskap, revisjonsmerknader og deterministisk nøkkeltallsanalyse.
- `ANNOUNCEMENTS_STATUS`: åpne kunngjøringer, konkurs/tvang/oppløsning og registrert status.
- `HISTORICAL_WEB`: historiske snapshots fra kjente domener/URL-er.
- `DOMAINS_DIGITAL`: domener, RDAP og offentlig selskapsweb/infrastruktur i passiv modus.
- `PUBLIC_PROFILES`: offentlig tilgjengelige profiler; svak identitetsvekt og aldri automatisk identitetsbevis.
- `SANCTIONS`: offisielle sanksjonslister med konservativ entity resolution.

Sensitive kategorier og straffedom-/lovovertredelsesdata er ikke vanlige scope-moduler og forblir policy-gated/disabled som beskrevet i `PRIVACY_LEGAL.md`.

## Expansion policy
Hver investigation har én expansion policy:

- `CONTEXT_ONLY`: relaterte entities vises som kontekst, men undersøkes ikke videre automatisk.
- `DIRECT_RELATIONS`: direkte, dokumenterte og relevante relasjoner kan undersøkes innen aktivt scope.
- `MATERIAL_RELATIONS`: direkte eller indirekte relasjoner kan undersøkes når planner dokumenterer hvorfor de er vesentlige for et aktivt informasjonsbehov.

Standard er `CONTEXT_ONLY` for personundersøkelser og `DIRECT_RELATIONS` for virksomhetsundersøkelser.

## Relasjonsdybde
`max_relation_depth` begrenser hvor langt systemet kan ekspandere fra mål-entity. Dette kommer i tillegg til global `max_depth` for leads/actions.

Relasjonsdybde 0 = kun mål. 1 = direkte relasjoner. 2+ krever eksplisitt expansion policy som tillater det og et dokumentert informasjonsbehov.

## Hva som ikke auto-ekspanderes
Følgende skal normalt ikke utløse videre undersøkelse alene:
- samme navn,
- samme kommune,
- samme adresse uten annen støtte,
- omtalt i samme artikkel,
- sosial profil-likhet,
- revisor/regnskapsfører som profesjonell tjenesteyter,
- svak fuzzy-match mot sanksjons-/profilkilde.

Disse kan bli kontekst eller lead, men ikke automatisk ny full investigation.

## Materialitet
En relatert entity kan markeres `MATERIAL` når den er nødvendig for å besvare et aktivt scope-spørsmål. Eksempler:
- målperson er daglig leder/styreleder i virksomheten og `BUSINESS_ROLES`/`FINANCIALS` er aktivert,
- virksomheten er offisielt mor-/datterselskap og `COMPANY_NETWORK` er aktivert,
- et dokumentert selskap er nødvendig for å løse en identitetskonflikt.

Materialitet skal ha eksplisitt `reason` og audit event.

## Scope-endringer underveis
Brukeren kan utvide eller innsnevre scope. Utvidelse skal audit-logges og kan åpne nye leads. Innsnevring stopper nye actions i modulen, men sletter ikke allerede innsamlet evidens automatisk; retention/deletion følger egen policy.

## Source availability vs scope
`config/sources.yaml` beskriver hva systemet **kan** bruke. Investigation scope beskriver hva systemet **får** bruke i den konkrete saken.

En enabled source er derfor ikke automatisk aktiv i alle investigations.

## Report semantics
Rapporten skal eksplisitt vise:
- hvilke moduler som ble undersøkt,
- hvilke moduler som ikke ble undersøkt,
- expansion policy og relasjonsdybde,
- vesentlige coverage-gaps og stop reason per modul.

Fravær av funn i en deaktivert eller ufullstendig modul skal aldri presenteres som et negativt funn.