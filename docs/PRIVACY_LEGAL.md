# Personvern og juridiske grenser

Dette er tekniske produktkrav, ikke juridisk rådgivning.

## Åpent på nett er fortsatt personopplysninger
Offentlig tilgjengelig informasjon kan fortsatt være omfattet av GDPR/personopplysningsloven. Hver investigation skal ha eksplisitt `purpose`, operatør og retention policy. Dataminimering gjelder gjennom hele pipeline.

## Særlige kategorier
Systemet skal ikke inferere/profilere helse, religion/livssyn, etnisitet, seksuell orientering eller politiske meninger. Kilder som typisk eksponerer slike kategorier er disabled by default.

## Straffedommer/lovovertredelser
GDPR artikkel 10 og personopplysningsloven § 11 gir særregler; omfattende registre over straffedommer kan bare føres under offentlig myndighets kontroll. Derfor er generell straffedom-indexering og personbasert court-record harvesting ikke del av standardproduktet. Juridiske dokumenter kan behandles case-by-case når det foreligger riktig formål/hjemmel og policy tillater det.

## Fødselsnummer
Ikke hent, lagre eller bruk fødselsnummer som standard. BRREG sin åpne rolle-totalbestand gir fødselsdato; fødselsnummer-endepunkter er tilgangsstyrte. Personopplysningsloven § 12 krever saklig behov og nødvendighet for entydige identifikasjonsmidler.

## Reelle rettighetshavere
API-et er tilgangsstyrt til bestemte kategorier. Adapter skal være disabled med mindre operatøren dokumenterer berettiget tilgang og Maskinporten-konfigurasjon.

## Automatiserte beslutninger
Analysen skal være et research-/rapporteringsverktøy, ikke en svart-boks beslutningsmotor for ansettelse, kreditt, forsikring, bolig eller andre høy-konsekvensavgjørelser. Ingen generell person-risikoscore.

## Retention/deletion
Raw evidence og reports får retention policy. Minimér snapshots av persondata. Implementer sletting/export per investigation og audit av tilgang.

## Referanser
- https://lovdata.no/dokument/NL/lov/2018-06-15-38/gdpr/ARTIKKEL_10
- https://lovdata.no/nav/andre-rettskilder/Personopplysningsloven/kap3
- https://www.datatilsynet.no/
- https://www.brreg.no/bruke-data-fra-bronnoysundregistrene/datasett-og-api/data-om-reelle-rettighetshavere/
