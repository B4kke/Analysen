# UI/UX

## New investigation
Input:
- target: person/virksomhet/domain,
- kjente identifiers,
- formål,
- eksplisitt scope-moduler,
- expansion policy,
- max relation depth.

Identitetsavklaring er alltid aktiv som systemhygiene og vises som obligatorisk.

### Scope-valg
Brukeren kan huke av:
- Web og medieomtale
- Virksomhetsroller
- Selskapsrelasjoner
- Regnskap og økonomi
- Kunngjøringer / virksomhetsstatus
- Historiske nettsider
- Domener / digitalt fotavtrykk
- Offentlige profiler
- Sanksjonskontroll

Standard skal være konservativt. Personundersøkelser skal ikke automatisk få full selskaps-/finansresearch.

### Expansion policy
UI forklarer:
- `Kun som kontekst`
- `Undersøk direkte relasjoner`
- `Undersøk vesentlige relasjoner automatisk`

Vis max relation depth eksplisitt.

## Live investigation
Live event stream viser hvilken modul/kilde som arbeider, hvilken type spørsmål som undersøkes og hva som er funnet uten å vise skjult chain-of-thought.

Eksempel events:
- Identitet: kandidat avklart mot BRREG rolledata
- Web/media: 18 discovery-kandidater
- Lead: historisk virksomhetsnavn utløste målrettet søk
- Verification: claim mangler rolleperiode; nytt verification lead
- Scope: relatert selskap lagret som context-only, ikke videre undersøkt
- Stop: web/media ferdig — ingen nye high-value leads

## Module cards
Hver aktiv scope-modul har eget kort med:
- status,
- antall queries/lookups,
- kandidater/dokumenter,
- relevante funn,
- open gaps,
- stop reason.

Ikke-valgte moduler vises som `IKKE UNDERSØKT`, ikke som tomme/funnløse.

## Graph
Cytoscape nodes: Person, Company/Organization, Address, Domain, Document. Edges viser predicate og resolution state. Klikk edge -> evidence drawer med hvorfor koblingen finnes.

Entity-stater skal visuelt skilles:
- target/material/researched,
- context-only,
- unresolved identity,
- not-match/blocked.

En context-only node skal ikke se ut som en full bakgrunnssjekket entity.

## Evidence
Filter på claim status/source tier/date/module. Side-by-side claim og supporting/contradicting evidence. Manual identity merge/split og materiality-markering krever begrunnelse og audit event.

## Search scope / coverage
Egen visning viser:
- hvilke providers/kilder som ble brukt,
- query classes,
- tidsrom,
- utilgjengelige kilder,
- stop reason,
- kjente gaps.

Dette gjør «ikke funnet» etterprøvbart uten å overdrive dekningen.

## Report
Draft/Reviewed/Final. Klikkbare citations. Uverifiserte leads skal aldri visuelt blandes med bekreftede funn.

Rapporten viser tydelig `UNDERSØKT`, `IKKE UNDERSØKT` og `UNDERSØKT MED GAPS` per modul.

## Mobil
Alle primære views skal være responsive. Graf får liste-/timeline-fallback på liten skjerm; evidence drawer blir full-screen sheet. Scope-valg og module cards skal fungere uten horisontal scrolling.
