# Finansanalyse

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

## Going concern/revisjonsmerknader
Må støttes med konkret tekst fra revisjonsberetning/note og markeres med år. LLM får relevant utdrag + strukturerte tall, ikke bare filnavnet.

## Datakvalitet
Årsregnskap kan variere i layout/taksonomi. Extraction får `native`, `table`, `ocr` eller `vlm` provenance og quality flag. Materiale tall bør kryssjekkes mot totalsummer/balanseidentitet der mulig.
