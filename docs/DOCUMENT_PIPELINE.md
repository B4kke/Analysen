# Dokumentpipeline

## Inntak
MIME sniff -> raw snapshot/hash -> parser routing -> normalized document -> chunk/layout -> extraction.

## Parsere
- HTML: Trafilatura/Crawl4AI.
- PDF: PyMuPDF først.
- XLSX: openpyxl.
- DOCX: python-docx.
- CSV/JSON: native parser.
- Scannet/komplisert: OCR/VLM fallback.

## Årsregnskap
1. Hent tilgjengelige år fra Regnskapsregisteret.
2. Snapshot PDF.
3. Parse native text/tabeller.
4. OCR/VLM kun for manglende segmenter.
5. Normaliser norske regnskapslinjer til intern taxonomi.
6. Beregn nøkkeltall deterministisk.
7. LLM tolker kun normaliserte tall + kildeutdrag.

## Nøkkeltall
Eksempel: revenue growth, operating margin, net margin, equity ratio, debt ratio, current ratio. Formler versjoneres og lagres med beregningen.

## Multimodal
Kimi K3/Nano Omni kan brukes til visuelt vanskelige sider. VLM-output er extracted candidate data og må ha side/region provenance samt verifikasjon mot dokumentet.
