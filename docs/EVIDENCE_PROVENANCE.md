# Evidence & provenance

## Regel
En material report sentence skal kunne spores: `report sentence -> claim -> claim_evidence -> evidence -> document snapshot -> source URL`.

## Evidence-locatorer
- Web: tekst-offset eller selector + kort supporting excerpt.
- JSON API: JSONPath + normalisert feltverdi + raw payload hash.
- PDF: side + bbox/tekstområde der mulig.
- Tabell: side/sheet + row/column.

## Snapshot
Lagre originalrespons/dokument før transformasjon når lisens og personvern tillater det. Beregn SHA-256 og hentetid. Snapshot er immutable; ny henting gir ny versjon.

## Discovery
SearXNG/GDELT snippets kan opprette `SearchResult` og leads, men aldri `Evidence` uten at originalen hentes.

## Confidence
Ingen enkel LLM-prosent. Confidence bygges av observerbare komponenter: identity strength, source tier, corroboration, temporal consistency, extraction validity og contradiction state. Presenter til bruker primært som state, ikke falsk presisjon.

## Negative evidence
«Ikke funnet» er ikke «finnes ikke». Rapportgeneratoren må uttrykke search scope og manglende funn presist.

## Contradictions
Behold begge versjoner og evidens. Verifier kan foreslå årsak (f.eks. ulike perioder), men må ikke slette motstridende fakta.
