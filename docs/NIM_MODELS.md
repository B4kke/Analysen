# NVIDIA NIM modellstrategi — 2026-09-17

NIM brukes via `https://integrate.api.nvidia.com/v1` og OpenAI-kompatible endepunkter. Modellvalg ligger i `config/models.yaml`.

## Viktig om norsk
NVIDIA sine modellkort for Nemotron 3 Super/Ultra og Nemotron 3.5 Lightning lister ikke norsk som offisielt støttet språk. De kan fortsatt fungere godt, men norsk kvalitet må måles i vårt eget eval-sett. Gemma 4 31B IT oppgir støtte for over 140 språk og er derfor en viktig norsk/multilingual canary og VLM-kandidat.

## Anbefalt rollefordeling

### 1. Planner / vanskelig hypotese- og nettverksanalyse
**Primary:** `nvidia/nemotron-3-super-120b-a12b`
- gratis hosted endpoint
- opptil 1M context
- agentic workflows, RAG, tool use og lang kontekst
- default planner

**Deep:** `nvidia/nemotron-3-ultra-550b-a55b`
- gratis hosted endpoint
- opptil 1M context
- frontier reasoning, komplekse agentiske workflows og verifikasjon
- brukes selektivt ved vanskelige saker

**Norwegian/multimodal canary:** `google/gemma-4-31b-it`
- gratis hosted endpoint
- 256K context
- text + image + video
- 140+ språk
- sterk kandidat når norsk språkforståelse eller visuell kontekst er viktig

### 2. Research workhorse / sub-agenter / query generation
**Primary:** `nvidia/nemotron-3.5-lightning-30b-a3b`
- gratis hosted endpoint
- svært lav aktiv parameterkostnad (3B active / 30B total)
- laget for long-running agents og høy throughput
- brukes til søkequeryer, klassifisering, lead-generation og enkle deloppgaver

**Fallback:** `nvidia/nemotron-3-super-120b-a12b`.

Merk: Lightning oppgir ikke norsk blant de offisielt støttede språkene; den må benchmarkes på norsk før den får ansvar for material findings.

### 3. Factual extraction til schema
**Primary:** Lightning for høyvolums extraction når schema-output holder mål.

**Norwegian fallback:** `google/gemma-4-31b-it`.

**Deep:** Super ved komplekse juridiske/finansielle dokumenter.

Regel: output valideres med Pydantic; ugyldig output retryes/eskaleres og lagres aldri halvveis.

### 4. Claim verification / contradiction analysis
**Primary:** Ultra for material findings.

**Routine fallback:** Super.

**Norwegian fallback/canary:** Gemma 4 31B dersom norsk tekstkvalitet eller instruksjonsfølging er bedre i våre evals.

Verifier får bare claim + konkret evidence; ikke hele fri web-konteksten hvis det kan unngås.

### 5. Rapportforfatter
**Primary:** Super.

**Deep:** Ultra for store saker med lang tidslinje/nettverk.

**Norwegian fallback/canary:** Gemma 4 31B.

Rapportmodell får verified claim objects, ikke frie søkeresultater.

### 6. Multimodal dokumenter/bilder
**Primary:** `google/gemma-4-31b-it`.
- multimodal text/image/video
- 140+ språk
- egnet til norsk bilde-/dokumentforståelse, OCR-lignende lesing og visuell kontekst

**Fallback:** `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`.
- image/video/audio/text
- god dokument- og multimodal reasoning
- modellkortet oppgir English-only; skal derfor ikke være norsk primærmodell

Kimi K3 er fjernet fra default routing på grunn av observert latency i vår bruk.

Før VLM: prøv alltid native PDF/text/table parsing; VLM er fallback eller brukes når bilde/layout faktisk bærer informasjonen.

### 7. Embeddings
**Primary:** `nvidia/nemotron-3-embed-1b` (hosted Free Endpoint) for semantic retrieval/candidate generation.

Embeddings brukes til kandidatgenerering og likhet, aldri alene til å bekrefte identitet eller en påstand. Norsk retrieval må benchmarkes eksplisitt; vi skal ikke anta språkstøtte som ikke er dokumentert.

## Ikke nødvendig i MVP som hosted-avhengighet
`nemotron-parse-2.0`, `nemotron-ocr-v2` og flere rerank-modeller er interessante, men dersom de bare er self-hosted/downloadable skal de ikke være krav for MVP. Pipeline skal være provider-agnostisk.

## Routing
- `fast`: Nemotron 3.5 Lightning
- `balanced`: Nemotron 3 Super
- `deep`: Nemotron 3 Ultra
- `norwegian_multilingual`: Gemma 4 31B IT
- `vision`: Gemma 4 31B IT -> Nemotron Nano Omni fallback
- `embed`: Nemotron 3 Embed 1B

Escaler ved: lav extraction confidence, motstridende evidence, lang kompleks tidslinje, uavklart entity resolution, material finding eller svak norsk output.

## Eval før modellbytte
Mål minst:
- norsk entity extraction F1
- norsk claim-verifikasjon
- JSON/schema validity
- citation entailment
- same-name disambiguation
- contradiction precision
- tool-call validity
- bilde/OCR-kvalitet på norske dokumenter
- time-to-first-token
- total latency
- tokens/s
- tokens per completed investigation

## Verifiserte NIM-kilder per 2026-09-17
- https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b
- https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b
- https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b
- https://build.nvidia.com/google/gemma-4-31b-it
- https://build.nvidia.com/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
- https://build.nvidia.com/models?q=embed
- https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html
