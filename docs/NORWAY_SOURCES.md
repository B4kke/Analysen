# Norske kilder — prioritet og bruk

Dette dokumentet skiller mellom **implementert**, **verifisert kandidat** og **begrenset/disabled**. En kilde skal ikke markeres aktiv bare fordi den kan åpnes i nettleseren.

## Tier 1: Brønnøysundregistrene
Base: `https://data.brreg.no/enhetsregisteret/`
Lisens: NLOD 2.0 for åpne Enhetsregister-data.

### Enheter
- `/api/enheter`
- `/api/enheter/{orgnr}`

Bruk: orgnr, navn, historiske navn, organisasjonsform, adresser, næringskode, statuser, registreringsdata og lenker.

### Roller per virksomhet
- `/api/enheter/{orgnr}/roller`

Bruk: styre, daglig leder, revisor, regnskapsfører m.m. Lagre kildefeltene, ikke bare LLM-oppsummering.

### Åpen totalbestand roller
- `/api/roller/totalbestand`

Zippet JSON, inkluderer fødselsdato. Dette er hovedgrunnlaget for lokal reverse-index fra person til virksomhetsroller.

**Ikke bruk** `/autorisert-api/roller/totalbestand` eller personrolleoppslag med fødselsnummer uten Maskinporten-scope og riktig hjemmel.

### Juridiske roller
- `/api/roller/enheter/{orgnr}/juridiskeroller`

Finn hvilke andre organisasjoner en virksomhet har roller i, for eksempel deltaker, regnskapsfører eller revisor.

### Konsernstruktur
- `/api/konsernstruktur/{orgnr}`

Bruk for hierarkiske selskapsrelasjoner der data finnes.

### Rolleoppdateringer
- `/api/oppdateringer/roller`

Bruk senere til inkrementell oppdatering av lokal indeks.

## Tier 1: Regnskapsregisteret
Base: `https://data.brreg.no/regnskapsregisteret/regnskap/`

- tilgjengelige år for årsregnskap
- PDF-kopi per orgnr/år
- opptil siste 15 år

Pipeline: hent år -> snapshot PDF -> native parse -> tabeller -> OCR/VLM fallback -> normaliser regnskap -> beregn ratios i kode.

## Tier 1: BRREG kunngjøringer
`https://www.brreg.no/registersok/kunngjoringer/`

Konkursregisteret publiserer blant annet åpning/endring/avslutning av bobehandling, tvangsavvikling og tvangsoppløsning. Web-adapter må følge nettstedets vilkår/rate limits; ikke anta et API som ikke er dokumentert.

## Implementert: Nasjonalbiblioteket

Autoritativ detaljspesifikasjon: `docs/NATIONAL_LIBRARY.md`.

Analysen bruker NB som en **mixed-rights** historisk mediekilde, ikke som et
enkelt metadata-API. Den implementerte kjeden er:

`target/verified alias -> nb_newspaper_search -> Catalog FULL_TEXT_SEARCH -> raw snapshot -> issue candidate -> item-level rights gate -> contentfragments page locator -> IIIF xywh -> DH-lab context -> permitted page/crop OCR -> MediaMention -> identity resolution -> Evidence/Claim -> verifier -> report`.

Live Catalog-parseren håndterer den observerte grupperte responsformen under
`_embedded.mediaTypeResults[].result._embedded.items` i tillegg til eldre
flatare responsformer.

Rettighetsreglene er konservative:
- `LIBRARY_ONLY`, `NB_ONLY` og ukjent/ufullstendig rights-metadata blokkerer sidehenting.
- `PUBLIC_VIEW_ONLY` kan tillate rettighetsgodkjent in-memory behandling og avledet crop, men full side lagres ikke og bildet embeddes ikke i rapport.
- `PUBLIC_REUSE` krever eksplisitt gjenbruksgrunnlag før rapport-embedding.
- Ingen innloggings-, pliktavleverings-, geografi-, token- eller annen tilgangsbypass.

Et avisnavnetreff er aldri identitetsbevis. Mediefunn starter `UNRESOLVED`.
Deterministisk identitetsvurdering kan bare promotere med corroborerende
target-signaler; `MATCH` blir verifier-støttet claim, mens
`PROBABLE_MATCH` bare kan gi delvis/context-støtte.

## Verifiserte kandidater — høy prioritet

### Finanstilsynets virksomhetsregister
API: `https://api.finanstilsynet.no/registry/`

Offisielt åpent API for juridiske enheter, personer eller selskaper med lisenser/autorisasjoner knyttet til virksomhet i Norge eller norske godkjenninger brukt i utlandet.

**Bruk:** bekrefte regulatorisk status, konsesjonstype og profesjonell/finansiell virksomhetskontekst.  
**Status:** kandidat; implementer typed adapter + eksakt/orgnr-søk før aktivering.

### Patentstyrets åpne registerdata
Portal: `https://developer.patentstyret.no/`

Offentlige patent-, varemerke- og designsaker med søkernavn, ID-er, datoer, status og hendelser. Norske virksomheter kan ofte kobles entydig via organisasjonsnummer. Dataene oppdateres løpende.

**Bruk:** IP-eierskap/-søknader, historiske virksomhetsnavn, produkt-/varemerkeforbindelser og nye company leads.  
**Tilgang:** åpent datasett/NLOD, men API-et krever login/subscription key. Ikke aktiver før secret-konfig og adapter er på plass.

### Doffin Public API
Offisiell API-guide ligger i `anskaffelser/eforms-sdk-nor/docs/doffin-api.md`.

Public API er eksplisitt laget for maskinlesbart søk og nedlasting av publiserte Doffin-kunngjøringer.

**Bruk:** offentlig innkjøpshistorikk, oppdragsgiver/leverandørrelasjoner, tildelinger og kontraktskontekst.  
**Tilgang:** registrering/subscription kreves. Bruk Public API; ikke Notices API for research.

### eInnsyn
Base: `https://api.einnsyn.no`  
Spesifikasjon: `felleslosninger/einnsyn-api-spec`.

API-et støtter blant annet søk og journal-/dokumentmetadata, men bruker API-key-header.

**Bruk:** postjournaler, offentlige saks-/dokumentspor og konkrete myndighetsrelasjoner.  
**Tilgang:** API-nøkkel. Ingen automatisk bestilling av innsyn som del av standard research-loop.

### Arbeidstilsynet — bemanningsforetak
- API/direkte datasett: `https://data.arbeidstilsynet.no/bemanningsforetaksregisteret2/api`

Kontinuerlig oppdatert informasjon om godkjenningsstatus, orgnr, navn, næringskode, ansatte og adresser.

**Bruk:** sektor-gate når virksomheten driver bemanning/utleie av arbeidskraft.

### Arbeidstilsynet — renholdsregister
- `https://registerdata.arbeidstilsynet.no/renhold_register.xml`
- NLOD, daglig oppdatert.

**Bruk:** bekrefte godkjent/under-behandling-status for renholdsvirksomheter.

### Direktoratet for byggkvalitet — Sentral godkjenning
- API: `https://sgregister.dibk.no/api`

Åpent og gratis REST-API uten registrering. DiBK anbefaler at data normalt slås opp direkte/regelmessig fremfor å lagres permanent.

**Bruk:** bygg-/anleggsvirksomheter og dokumentert sentral godkjenning.  
**Lagring:** evidensier claim/lookup, men respekter kildeanbefalingen og unngå unødvendig speiling av hele registeret.

## Verifiserte kandidater — situasjonsbestemt

### Kartverket Adresse REST-API
Kartverkets adresse-API krever ikke registrering og søker i adresseinformasjon fra matrikkelen.

**Bruk:** normalisere adresse, kommune, poststed og geografi som entity-resolution-signal.  
**Viktig:** dette er **ikke** en åpen eier-/grunnbokskilde. Ikke inferer eierskap fra adresse-API.

### Mattilsynet Smilefjes
- komplett CSV: `https://smilefjes.mattilsynet.no/api/tilsyn.csv`
- CC BY 4.0
- tilsynshistorikk siden 2016 for serveringssteder.

**Bruk:** sektor-spesifikk myndighetshistorikk for restaurant/servering. Tilsynsfunn er observasjoner fra en bestemt dato, ikke en generell virksomhetskarakteristikk.

### Fiskeridirektoratets fartøyregister
- API: `https://api.fiskeridir.no/vessel-api/`
- NLOD 2.0
- fartøy- og eieropplysninger.

**Bruk:** virksomheter/personer med dokumentert maritim/fiskerirelasjon. Ikke kjør for alle targets.

Fiskeridirektoratet har også andre offentlige API-er (bl.a. akvakultur-/autorisasjonsregistre) som bør vurderes etter sektor-trigger.

### Luftfartstilsynet — Norges luftfartøyregister
- JSON: `https://data.caa.no/nlr/norgesluftfartoyregister.json`
- autoritativ kilde, oppdatert daglig.

Datasettet inneholder registreringsmerke, type/produsent, serienummer, luftdyktighetsinformasjon og offentlige opplysninger om juridiske personer/organisasjoner som eiere, inkludert orgnr når tilgjengelig.

**Bruk:** verifisert luftfartøy-/eierrelasjon når ASSETS/AVIATION-lignende scope senere finnes. Ikke bruk fravær av orgnr som bevis på fravær av eier, siden datasettet kan være ufullstendig på enkelte felt.

### Tilskudd.no
Landingsside: `https://tilskudd.dfo.no/`

Gir oversikt over statlige tilskuddsordninger, tildelinger og mottakere, med registrerte tildelinger fra 2021 og eksportmulighet til Excel.

**Bruk:** organisasjons-/virksomhetskontekst rundt dokumenterte statlige tilskudd. Ikke opprett personprofil bare fordi en privat mottaker finnes i datasettet.  
**Teknisk:** ingen registrert API per nå; implementer dokumentert fil-/eksportinngest hvis kilden prioriteres.

### Sokkeldirektoratet — FactMaps/utvinningstillatelser
Sokkeldirektoratet publiserer åpne FactMaps REST/WFS-data om blant annet brønner, funn, felt og utvinningstillatelser under NLOD 1.0.

**Bruk:** sektor-spesifikk selskapskontekst for petroleum/offshore, inkludert lisenser/operatørforhold. Ikke kjør mot ordinære targets uten dokumentert bransjerelevans.

## Source discovery: data.norge.no
Data.norge.no brukes som **katalog for å finne nye offentlige datasett/API-er**, ikke som evidens for claims om target når originalregisteret kan brukes.

Når en ny kandidat oppdages:
1. finn original utgiver,
2. verifiser endpoint, lisens, tilgang og aktualitet,
3. dokumenter lagrings-/rate-vilkår,
4. lag typed adapter + fixture/contract-test,
5. aktiver først etter dette.

## Register over reelle rettighetshavere
`https://www.brreg.no/bruke-data-fra-bronnoysundregistrene/datasett-og-api/data-om-reelle-rettighetshavere/`

Tilgangen er rolle-/formålsstyrt via Maskinporten. **Deaktivert som standard.** Implementer kun adapter dersom operatøren dokumenterer kvalifisert tilgang.

## Domstoler og rettsavgjørelser
Høyesterett publiserer avgjørelser på domstol.no. Dette kan brukes til juridisk research på dokumentnivå, men må ikke bli et omfattende register over straffedommer for privatpersoner. Straffedom/lovovertredelsesdata er policy-disabled som standard og krever separat juridisk gate.

## Lovdata
Brukes som rettskilde for lover/forskrifter, ikke som automatisk personregister. Respekter tilgangsvilkår og åpne/offentlige deler.

## Medier
Søk via SearXNG og hent originalartikkel der den er offentlig tilgjengelig. Bruk NB for historisk/digitalisert materiale. Lagre publisher, publiseringsdato, URL, tittel og relevant tekst bare når capture-policy tillater det. Snippets er discovery.

## Kilder som ikke er grunnmur
Kommersielle kataloger som Proff/Purehelp kan ha nyttig UI, men MVP skal ikke være avhengig av dem eller skrape dem uten tillatelse. Sosiale nettverk brukes kun når innholdet er faktisk offentlig og lovlig tilgjengelig; ingen innlogging/bypass.

## Sensitive/politiske data
BRREG har også partiregisterdata. Disse er **ikke** del av default background-check pipeline. Politisk tilknytning/meninger er sensitive og skal ikke infereres eller profileres.

## Referanser
- https://api.nb.no/
- https://www.nb.no/services/image/swagger/api-doc.html
- https://data.brreg.no/enhetsregisteret/api/dokumentasjon/no/index.html
- https://data.brreg.no/regnskapsregisteret/regnskap/swagger-ui/swagger-ui/index.html?urls.primaryName=aarsregnskap
- https://www.finanstilsynet.no/analyser-og-statistikk/api-for-apne-data/
- https://developer.patentstyret.no/
- https://github.com/anskaffelser/eforms-sdk-nor/blob/main/docs/doffin-api.md
- https://github.com/felleslosninger/einnsyn-api-spec
- https://openapi.arbeidstilsynet.no/
- https://sgregister.dibk.no/apidocs/index.html
- https://www.kartverket.no/api-og-data/eiendomsdata/brukarrettleiing-adresse-api
- https://smilefjes.mattilsynet.no/api/tilsyn.csv
- https://api.fiskeridir.no/vessel-api/
