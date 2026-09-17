# Norske kilder — prioritet og bruk

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
Finn hvilke andre organisasjoner en virksomhet har roller i (f.eks. deltaker, regnskapsfører, revisor).

### Konsernstruktur
- `/api/konsernstruktur/{orgnr}`
Nytt i 2026. Bruk for hierarkiske selskapsrelasjoner der data finnes.

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
Konkursregisteret publiserer bl.a. åpning/endring/avslutning av bobehandling, tvangsavvikling og tvangsoppløsning. Web-adapter må følge nettstedets vilkår/rate limits; ikke anta et API som ikke er dokumentert.

## Register over reelle rettighetshavere
`https://www.brreg.no/bruke-data-fra-bronnoysundregistrene/datasett-og-api/data-om-reelle-rettighetshavere/`
Tilgangen er rolle-/formålsstyrt via Maskinporten. **Deaktivert som standard.** Implementer kun adapter dersom operatøren dokumenterer kvalifisert tilgang.

## Domstoler og rettsavgjørelser
Høyesterett publiserer avgjørelser på domstol.no. Dette kan brukes til juridisk research på dokumentnivå, men må ikke bli et omfattende register over straffedommer for privatpersoner. Straffedom/lovovertredelsesdata er policy-disabled som standard og krever separat juridisk gate.

## Lovdata
Brukes som rettskilde for lover/forskrifter, ikke som automatisk «personregister». Respekter tilgangsvilkår og åpne/offentlige deler.

## Medier
Søk via SearXNG og hent originalartikkel der den er offentlig tilgjengelig. Lagre publisher, publiseringsdato, URL, tittel og relevant tekst. Snippets er kun discovery.

## Offentlige virksomhetskilder
For selskapsspor kan adaptere senere legges til for Doffin, offentlige postjournaler eller andre åpne datasett når formål, tilgang og lisens er dokumentert. Ikke aktiver en kilde bare fordi den kan skrapes.

## Kilder som ikke er grunnmur
Kommersielle kataloger som Proff/Purehelp kan ha nyttig UI, men MVP skal ikke være avhengig av dem eller skrape dem uten tillatelse. Sosiale nettverk brukes kun når innholdet er faktisk offentlig og lovlig tilgjengelig; ingen innlogging/bypass.

## Sensitive/politiske data
BRREG har også partiregisterdata. Disse er **ikke** del av default background-check pipeline. Politisk tilknytning/meninger er sensitive og skal ikke infereres eller profileres.

## Referanser
- https://data.brreg.no/enhetsregisteret/api/dokumentasjon/no/index.html
- https://data.brreg.no/regnskapsregisteret/regnskap/swagger-ui/swagger-ui/index.html?urls.primaryName=aarsregnskap
- https://www.brreg.no/registersok/kunngjoringer/om-kunngjoringer/kunngjoringer-fra-konkursregisteret/
- https://www.brreg.no/bruke-data-fra-bronnoysundregistrene/datasett-og-api/data-om-reelle-rettighetshavere/
- https://www.domstol.no/no/hoyesterett/avgjorelser/
