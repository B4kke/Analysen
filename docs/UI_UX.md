# UI/UX

## Investigation
Input: person/virksomhet, kjente identifiers, formål og mode. Live event stream viser hvilken kilde som hentes og hva som er funnet uten å vise skjult chain-of-thought.

Eksempel events:
- BRREG: virksomhet funnet
- Roller: 4 dokumenterte roller
- Lead: ny tilknyttet virksomhet
- Accounts: 2024/2025 tilgjengelig
- Web discovery: 18 kandidater
- Verification: 3 støttet, 1 motstrid

## Graph
Cytoscape nodes: Person, Company/Organization, Address, Domain, Document. Edges viser predicate og resolution state. Klikk edge -> evidence drawer med hvorfor koblingen finnes.

## Evidence
Filter på claim status/source tier/date. Side-by-side claim og supporting/contradicting evidence. Manual identity merge/split krever begrunnelse og audit event.

## Report
Draft/Reviewed/Final. Klikkbare citations. Uverifiserte leads skal aldri visuelt blandes med bekreftede funn.

## Mobil
Alle primære views skal være responsive. Graf får liste-/timeline-fallback på liten skjerm; evidence drawer blir full-screen sheet.
