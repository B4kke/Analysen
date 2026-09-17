# NVIDIA NIM modellstrategi — 2026-09-17

NIM brukes via `https://integrate.api.nvidia.com/v1` og OpenAI-kompatible endepunkter. Modellvalg ligger i `config/models.yaml`.

## Viktig om norsk
NVIDIA sine modellkort for Nemotron 3 Super/Ultra og Nemotron 3.5 Lightning lister ikke norsk som offisielt støttet språk. De kan fortsatt fungere, men norsk kvalitet må måles i vårt eget eval-sett. Derfor har hver rolle primary/fallback/canary og må kunne byttes uten kodeendring.

## Anbefalt rollefordeling

### 1. Planner / vanskelig hypotese- og nettverksanalyse
**Primary:** `nvidia/nemotron-3-ultra-550b-a55b`
- 1M context
- frontier reasoning, complex agentic workflows, tool use
- bruk selektivt på komplekse eller eskalerte saker

**Routine/fallback:** `nvidia/nemotron-3-super-120b-a12b`
- 1M context
- agentic workflows, RAG, tool use
- default planner når Ultra ikke er nødvendig

**Canary:** `z-ai/glm-5-3`
- 1M context
- reasoning + function/tool calling
- evalueres spesielt på norsk extraction/verifikasjon

### 2. Research workhorse / sub-agenter / query generation
**Primary:** `nvidia/nemotron-3.5-lightning-30b-a3b`
- 1M context
- designet for long-running autonomous agents/sub-agent workhorse
- brukes til høyvolums plan-delsteg, søkequeryer, klassifisering og enkel strukturering

**Fallback:** `nvidia/nemotron-3-super-120b-a12b`.

### 3. Factual extraction til schema
**Primary:** Lightning med reasoning lav/av og JSON mode når støttet.
**Escalation:** Super ved komplekse juridiske/finansielle dokumenter.
Regel: output valideres med Pydantic; ugyldig output retryes/eskaleres og lagres aldri halvveis.

### 4. Claim verification / contradiction analysis
**Primary:** Ultra for material findings.
**Routine:** Super.
Verifier får bare claim + konkret evidence; ikke hele fri web-konteksten hvis det kan unngås.

### 5. Rapportforfatter
**Primary:** Super.
**Escalation:** Ultra for store saker med lang tidslinje/nettverk.
Rapportmodell får verified claim objects, ikke frie søkeresultater.

### 6. Multimodal dokumenter/bilder
**Primary:** `moonshotai/kimi-k3` via NIM for vanskelige multimodale dokumenter (1M context, text+image).
**Focused fallback:** `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` for image/video/audio/text og OCR-lignende forståelse.
Før VLM: prøv alltid native PDF/text/table parsing; VLM er fallback.

### 7. Embeddings
**Primary:** `nvidia/nemotron-3-embed-1b` (hosted Free Endpoint) for semantic retrieval/candidate generation.
Embeddings kan aldri alene bekrefte identity eller claim.

## Ikke nødvendig i MVP
`nemotron-parse-2.0`, `nemotron-ocr-v2` og rerank-modeller kan være gode, men dersom de krever self-hosted NIM passer de dårlig som avhengighet på en maskin uten NVIDIA-GPU. Hold pipeline provider-agnostisk.

## Routing
- `cheap`: Lightning
- `balanced`: Super
- `deep`: Ultra
- `vision`: Kimi K3 -> Nano Omni fallback
- `embed`: Nemotron 3 Embed
- `canary`: GLM-5.3

Escaler fra cheap til balanced/deep ved: lav extraction confidence, motstridende evidence, lang kompleks tidslinje, uavklart entity resolution, eller material finding.

## Eval før modellbytte
Mål minst: JSON validity, citation entailment, Norwegian entity extraction F1, same-name disambiguation, contradiction precision, tool-call validity, latency og tokens per completed investigation.

## Kilder
- https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b
- https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b
- https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b
- https://build.nvidia.com/moonshotai/kimi-k3
- https://build.nvidia.com/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
- https://build.nvidia.com/models?q=embed
- https://build.nvidia.com/z-ai/glm-5-3
- https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html
