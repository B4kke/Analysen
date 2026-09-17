# Finansanalyse

## Scope gate
Finansanalyse kjøres bare når `FINANCIALS` er aktiv i investigation scope.

Et selskap analyseres finansielt bare når det er:
- selve target, eller
- eksplisitt markert `MATERIAL` med begrunnelse innen aktivt scope.

Det er ikke nok at virksomheten bare finnes som en node i grafen eller har svak/context-only relasjon til target.

## Prinsipp
LLM tolker; kode beregner. Alle tall beholder regnskapsår, valuta/enhet, kilde-PDF, side/locator og extraction status.

## Normalisert minimumsskjema
- revenue
- operating_income/operating_profit
- net_profit
- total_assets
- equity
- total_debt/liabilities
- current_assets
- current_liabilities
- cash
- auditor
- accounting_period

## Beregninger
- revenue growth = `(revenue_t - revenue_t-1) / abs(revenue_t-1)` når meningsfullt
- operating margin = operating_profit / revenue
- net margin = net_profit / revenue
- equity ratio = equity / assets
- debt ratio = debt / assets
- current ratio = current_assets / current_liabilities

Ingen deling på null; missing er `null`, ikke 0.

## Analyse
Trend over år, store avvik, negativ egenkapital, fall/stigning i inntekter, marginendring, revisorendring og eksplisitte noter kan bli leads. Dette er observasjoner, ikke automatisk «risiko» eller antydning om mislighold.

`FINANCIAL_ANOMALY` i `SEARCH_TRIGGERS.md` avgjør når ekstra dokument-/statusresearch er relevant.

Ekstra research skal normalt være målrettet mot:
- omkringliggende regnskapsår,
- noter,
- revisjonsberetning,
- revisorendring,
- åpne kunngjøringer/status.

Et finansielt avvik skal ikke automatisk starte full web-/personsøk uten separat trigger og aktivt scope.

## Going concern/revisjonsmerknader
Må støttes med konkret tekst fra revisjonsberetning/note og markeres med år. LLM får relevant utdrag + strukturerte tall, ikke bare filnavnet.

## Datakvalitet
Årsregnskap kan variere i layout/taksonomi. Extraction får `native`, `table`, `ocr` eller `vlm` provenance og quality flag. Materiale tall bør kryssjekkes mot totalsummer/balanseidentitet der mulig.

Dokumentkvalitetsfeil følger `DOCUMENT_QUALITY`-triggeren: prøv bedre parsing/OCR/VLM før man starter irrelevant websearch.
