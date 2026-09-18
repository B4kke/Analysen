# Search triggers and bounded follow-up research

Dette dokumentet er autoritativt for **når Analysen skal søke mer, hva det skal søkes etter, og når det skal stoppe**.

## Prinsipp
Nye søk skal ikke startes fordi «mer informasjon kan finnes». Hver action må være knyttet til et konkret `information_need`, aktivt scope og en forventet informasjonsgevinst.

Hver search/action skal kunne svare på:
- Hvilket spørsmål prøver vi å besvare?
- Hvilket funn eller hvilken usikkerhet trigget søket?
- Hvilken kildeklasse er best egnet?
- Hva vil bekrefte eller avkrefte hypotesen?
- Når er dette sporet ferdig?

## Trigger classes

### `IDENTITY_AMBIGUITY`
Når target eller relatert entity er tvetydig.

Søk/lookup:
- offisielle roller,
- virksomhetstilknytninger,
- sted/tidslinje,
- historiske navn/alias,
- andre sterke eller middels identitetssignaler.

Mål: `MATCH`, `NOT_MATCH` eller eksplisitt `UNRESOLVED`.

### `NEW_VERIFIED_ALIAS`
Når et historisk navn, virksomhetsnavn, domene eller annen verifisert alias oppdages.

Søk:
- eksakt alias,
- alias + allerede verifiserte identifikatorer,
- tidsavgrensede søk når aliaset har valid-time,
- Nasjonalbiblioteket når aliaset kan opptre i historiske aviser/publikasjoner.

### `MATERIAL_RELATION`
Når en dokumentert relasjon er relevant for aktiv scope-modul og expansion policy tillater videre research.

Eksempler:
- styreleder/daglig leder -> virksomhetskontekst,
- mor/datterselskap -> selskapsnettverk,
- kjent virksomhetsdomene -> domain/web research.

Sektorregistre (Finanstilsynet, Arbeidstilsynet, DiBK, Patentstyret, Fiskeridirektoratet m.fl.) skal bare brukes når target/relasjonen faktisk gjør registeret relevant og adapteren er aktivert.

### `WEAK_SOURCE_ONLY`
Når en material claim bare støttes av svak kilde.

Søk etter:
1. primær/offisiell kilde,
2. uavhengig sekundærkilde,
3. originaldokument.

### `CONTRADICTION`
Når to claims/evidence er logisk eller temporalt uforenlige.

Lag et målrettet disconfirmation/verification lead. Ikke gjør et nytt bredt personsøk.

### `TEMPORAL_GAP`
Når datoer, roller eller hendelser ikke passer sammen eller mangler overgang.

Søk:
- tidsbegrenset web,
- Nasjonalbibliotekets historiske avis-/publikasjonssøk når relevant,
- historiske snapshots,
- offisielle historikkfelt,
- dokumenter nær overgangstidspunktet.

### `FINANCIAL_ANOMALY`
Kun når `FINANCIALS` er aktiv og virksomheten er target eller `MATERIAL`.

Følg opp:
- omkringliggende regnskapsår,
- noter,
- revisjonsberetning,
- revisorendring,
- relevante kunngjøringer/status.

Et avvik er et observasjonssignal, ikke automatisk risiko/mislighold.

### `DOCUMENT_QUALITY`
Når et dokument ikke kan ekstraheres pålitelig.

Retry-rekkefølge:
1. alternativ native parser/layout,
2. tabell-/segmentparser,
3. OCR for manglende segment,
4. VLM for visuelt vanskelig region.

Dette skal normalt ikke trigge websearch.

### `DOMAIN_RELEVANCE`
Når et verifisert domene er relevant og `DOMAINS_DIGITAL` eller `HISTORICAL_WEB` er aktiv.

Bruk:
- direkte fetch,
- RDAP,
- Common Crawl/historiske snapshots,
- passiv link/discovery.

### `MEDIA_CORROBORATION`
Når en vesentlig påstand finnes i ett medium eller én sekundærkilde.

Hent originalartikkelen først. Søk deretter etter primærkilde eller uavhengig bekreftelse dersom påstanden er material. For eldre norsk presse/publikasjoner skal NB vurderes før bredere websearch.

NB-katalogtreff dokumenterer treff/publikasjon, men OCR-tekst kan bare persisteres når itemets `accessInfo` passerer capture-policy.

### `SANCTIONS_CANDIDATE`
Kun når `SANCTIONS` er aktiv.

Navnelikhet er aldri nok. Søk etter tillatte identitetssignaler som fødselsdato/-år, virksomhets-ID, land/sted og offisielle identifikatorer for å avgjøre match/ikke-match.

## Query classes
Planner velger query class før selve søkestrengen genereres:

- `IDENTIFIER_EXACT`
- `ENTITY_ALIAS_EXACT`
- `PERSON_COMPANY_RELATION`
- `TEMPORAL`
- `CONTRADICTION`
- `DOMAIN`
- `SOURCE_CONSTRAINED`
- `MEDIA_CORROBORATION`
- `DISCOVERY_BROAD`

`DISCOVERY_BROAD` skal brukes sparsomt og normalt bare tidlig i en aktiv web/media-modul eller når konkrete leads mangler.

## Source routing
Foretrekk den mest autoritative og målrettede kilden fremfor websearch:

- orgnr/enhet/status -> BRREG,
- roller -> BRREG rolle-API/lokal reverse-index,
- konsern -> BRREG konsernstruktur,
- regnskap -> Regnskapsregisteret,
- kunngjøringer -> BRREG offentlig kunngjøring,
- historisk norsk presse/publikasjon/alias -> Nasjonalbiblioteket,
- domene -> RDAP + offisiell nettside,
- historisk kjent URL/domene -> Common Crawl,
- generell omtale -> SearXNG,
- nyhetsdiscovery -> SearXNG/GDELT.

Når respektive adapter er implementert/aktivert:
- finansielle konsesjoner/autorisasjoner -> Finanstilsynet,
- patent/varemerke/design -> Patentstyret,
- offentlige anskaffelser -> Doffin Public API,
- offentlig journal-/dokumentmetadata -> eInnsyn,
- bemanning/renhold -> Arbeidstilsynet,
- sentral godkjenning bygg -> DiBK,
- adresse-normalisering -> Kartverket,
- serveringstilsyn -> Mattilsynet Smilefjes,
- fartøy/eierdata -> Fiskeridirektoratet.

Search-result snippets er discovery only. Originalkilden må hentes før claim/evidence. Et NB-metadataresultat er evidence for bibliografiske metadata, ikke automatisk for innholdet i OCR-treffet.

## Dataminimering i queries
Ikke send mer persondata til offentlig søkemotor enn nødvendig. Fødselsdato som finnes i lokal/offisiell indeks brukes primært internt til entity resolution og skal ikke automatisk inngå i webqueries.

Foretrekk kontekstuelle queries med virksomhet, rolle, sted eller tidsrom fremfor full fødselsdato.

## Verifier-triggered search
Verifier kan returnere et strukturert `missing_information`-behov når en material claim er `PARTIALLY_SUPPORTED`, `CONTRADICTED` eller `INSUFFICIENT_EVIDENCE`.

Dette kan opprette et nytt lead dersom:
- scope tillater det,
- informasjonen er vesentlig,
- samme spørsmål ikke allerede er uttømt,
- handlingen er innen budsjett.

## Stop conditions per lead/module
Stopp når ett eller flere gjelder:
- informasjonsbehovet er besvart med tilstrekkelig evidens,
- identiteten forblir eksplisitt `UNRESOLVED` etter relevante kilder,
- ingen nye high-value leads,
- nye treff er duplikater/irrelevante,
- repeated query/result loop,
- scope eller expansion policy blokkerer videre ekspansjon,
- kilde er utilgjengelig uten forbudt bypass,
- budsjett/depth/domain-limit nådd.

## Coverage ledger
Hver scope-modul skal føre maskinlesbar coverage:
- providers/sources forsøkt,
- query classes brukt,
- antall queries,
- kandidater og dokumenter hentet,
- tidsrom der relevant,
- kjent utilgjengelige kilder,
- stop reason,
- åpne gaps.

Dette brukes i rapporten til å beskrive søkeomfanget korrekt. «Ikke funnet» betyr aldri «finnes ikke».
