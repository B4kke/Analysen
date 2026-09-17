# NVIDIA NIM benchmark results for Analysen

Last updated: 2026-09-17

This file records observed benchmark results from the synthetic Norwegian test suite used by Analysen. Quality, formatting, latency, and hosted-endpoint availability are kept separate. A transport failure such as HTTP 503/529 or a read timeout is **not** counted as a model-quality failure unless the model actually returned an incorrect answer.

## Current working picture

- **Nemotron 3 Ultra 550B** is currently the strongest text/reasoning verifier in the Norwegian stress tests. It completed the focused Norwegian language suite at 21/21 exact fields and the long-context suite at 3/3 exact cases.
- **Nemotron 3 Super 120B** is very strong for general planning/reasoning and long-context work. It completed all three long-context placements exactly. Several missing stress-suite points came from hosted 503s or formatting rather than semantic errors.
- **Nemotron 3.5 Lightning 30B** is very useful as a fast workhorse/tool-calling model, but should not be the only verifier for linguistically difficult claims. Confirmed weaknesses include one double-negation error and occasional malformed/truncated structured JSON.
- **Gemma 4 31B IT** is exceptionally strong on exact Norwegian document OCR/vision, including difficult Unicode and adversarial images, but has shown one clear text-negation error and repeated visual arithmetic errors. Hosted 529 overloads also occur.
- **Nemotron 3 Embed 1B** is performing extremely well for Norwegian retrieval, including hard negatives, but temporal/status metadata filtering is still recommended because some cosine margins are small.
- **Nemotron Nano Omni 30B reasoning** is much faster than Gemma for vision in most observed calls, but Gemma has been slightly more exact on character-level OCR. Omni hosted availability has been materially worse in some vision-reasoning runs.

## Structured Norwegian extraction

Corrected production-style structured extraction tests use explicit JSON requirements and disable unnecessary reasoning for extraction tasks.

Observed results:

| Model | Result | Notes |
|---|---:|---|
| Nemotron 3 Super 120B | 100% on corrected structured set | Strong schema/extraction performance |
| Nemotron 3 Ultra 550B | 100% on corrected structured set | Strong schema/extraction performance |
| Gemma 4 31B IT | 100% on corrected structured set | Strong extraction; may wrap JSON in Markdown in non-response-format probes |
| Nemotron 3.5 Lightning 30B | Mostly correct | Earlier failure was largely harness/JSON-mode related; production-style JSON probe passed quickly |

### Production-style JSON probe

Same synthetic Norwegian identity-resolution problem using `response_format={"type":"json_object"}`.

Clean rerun:

| Model | Correct | Latency |
|---|---:|---:|
| Lightning, recommended sampling | PASS | 2.96 s |
| Lightning, deterministic | PASS | 9.49 s |
| Super | PASS | 1.26 s |
| Ultra | PASS | 11.78 s |
| Gemma | PASS | 8.92 s |

Important finding: forcing Lightning to temperature 0 was not faster or more reliable than NVIDIA-style recommended sampling.

## Norwegian language stress

Focused suite covers long compound words, incoming/current/former roles, modal uncertainty, difficult Nynorsk, passive voice, effective dates, Norwegian decimal/percent notation, Unicode addresses, and double negation.

| Model | Exact fields | Total | Availability notes |
|---|---:|---:|---|
| Ultra | 21 | 21 | No transport failure |
| Gemma | 20 | 21 | Last double-negation case lost to HTTP 529, not scored as semantic failure |
| Super | 18 | 21 | Entire 3-field Nynorsk case lost to HTTP 503; remaining available cases correct |
| Lightning | 17 | 21 | Contains confirmed quality/format failures |

Confirmed Lightning issues:

1. `Det er ikke riktig at selskapet aldri har hatt ansatte` was interpreted as `has_had_employees=false`. This is a genuine double-negation semantic error.
2. An effective-date case degenerated into malformed/truncated JSON and hit output length.
3. A difficult Nynorsk case understood the facts but labelled the language `no` instead of the requested `nynorsk` class.

Earlier broad stress-suite raw totals were Ultra 20/21, Super 19/21, Lightning 17/21 and Gemma 9/21, but these totals should **not** be used as rankings because several Gemma points were HTTP 529 failures and several Super/Ultra/Gemma apparent misses were formatting-only responses that were semantically correct.

## Long-context retrieval/reasoning

Synthetic context contains 260 Norwegian paragraphs with historical/invalid decoys and one valid record placed early, middle, or late.

| Model | Early | Middle | Late | Notes |
|---|---:|---:|---:|---|
| Ultra | PASS | PASS | PASS | 2.02 s / 1.66 s / 10.24 s |
| Super | PASS | PASS | PASS | 2.80 s / 1.62 s / 1.53 s |
| Lightning | PASS | PASS | FAIL | Middle required retry and 80.72 s; late returned unterminated JSON |
| Gemma | PASS | N/A | PASS | Middle was HTTP 529 overload; early 6.14 s, late 3.85 s |

This currently favors Super/Ultra for evidence synthesis over large retrieved bundles.

## Tool calling and agent loops

### Direct tool selection

Real NIM/OpenAI-compatible `tools` and `tool_choice=auto` were used. Lightning, Super, Ultra and Gemma all selected the correct synthetic company-registry tool with the correct organisation number on two runs.

Representative second run:

| Model | Tool/argument correct | Latency / availability |
|---|---:|---|
| Lightning | PASS | 1.12 s |
| Super | PASS | 5.60 s, 2 attempts |
| Ultra | PASS | 1.36 s |
| Gemma | PASS | 3.59 s |

### Two-step agent loop

Task: choose register tool -> receive synthetic registry result -> identify active chair, start date and source update date.

All four models returned 3/3 final fields correctly.

Observed first-step + final-step latencies in this run:

- Lightning: 31.48 + 1.55 s
- Super: 3.89 + 0.57 s, first step required retry
- Ultra: 23.64 + 4.23 s
- Gemma: 4.88 + 16.15 s

This demonstrates large hosted latency variance even when answer quality is perfect.

## Vision and OCR

### Difficult Norwegian document variants

Six variants included clean document, degraded JPEG, rotation, low contrast/noise, diagonal stamp and fax-like degradation. Documents contain Norwegian names and characters such as `Skjærgårdsforvaltning Øst AS`, `Åse Ødegård`, `Værøy`, and `Bjørn Sæther`.

- Gemma: **36/36 exact fields**
- Omni: **35/36 exact fields**

Omni's miss was a rotated-document layout error mixing `Signatur: Styrets leder alene` with the following `Prokura: Ingen registrert` line.

### Adversarial vision

Cases include instructions embedded inside the image, fully redacted fields that must not be guessed, current-vs-historical decoys, and confusable characters (`O/0`, `I/1`, `Æ/Ø/Å`).

- Gemma: **13/13 exact fields**
- Omni: **12/13 exact fields**

Both ignored image prompt injection and did not invent the redacted name. Omni misread `O0I1-ØRN-ÅS` as `OOII-ØRNAS`. Gemma read it exactly but the hardest identifier call required retry and took 49.92 s.

### Vision latency pattern

Omni is usually much faster on extraction, often around 1-5 seconds in the adversarial suite. Gemma is usually slower and more variable, but has so far been slightly better when every character must be exact.

## Multimodal reasoning / visual arithmetic

Ownership diagram: indirect `60% * 70% = 42%`, plus direct 10%, effective ownership 52%.

- Gemma: 3/3
- Omni: 3/3

Role timeline with historical decoy:

- Gemma: 2/2
- Omni: 2/2

### Initial invoice case

Correct values:

- subtotal ex VAT: 3117.50
- VAT: 779.38
- total inc VAT: 3896.88

Gemma returned 3025.50 / 756.38 / 3781.88, a genuine arithmetic/visual-reasoning failure. Omni could not be scored because both attempts received HTTP 503 `ResourceExhausted`.

### Isolated three-case vision-math suite

A second isolated run tested invoice arithmetic, financial-statement growth/margin, and signed bank-ledger totals.

Gemma:

- invoice VAT: **0/3**; returned 3126.50 / 781.63 / 3908.13
- accounts growth/margin: **1/2**; growth 23.00% correct, operating margin 21.93% instead of 21.95%
- signed ledger totals: **3/3**; credits 15600, debits 4650, net change 10950

This repeat confirms that Gemma's earlier invoice error was not an isolated one. It appears reliable at OCR and straightforward signed summation but should not be the sole calculator for visual financial tables.

Omni:

- invoice VAT: unavailable after read timeout/retry
- accounts growth/margin: unavailable after HTTP 503 `ResourceExhausted`
- signed ledger totals: **3/3**, but required retry and took 31.41 s

Omni therefore still lacks a clean quality score for the two harder visual-math cases; its failures here are availability failures, not semantic failures.

## Embeddings / retrieval

Model: `nvidia/nemotron-3-embed-1b`.

Initial Norwegian retrieval suite: **8/8 top-1**. Cases included Nynorsk, address synonyms, prokura/signature rights, financial paraphrases, uncertainty/negation and employment-law terminology.

Hard-negative suite: **6/6 top-1**. It correctly separated:

- current chair
- former chair
- incoming but not current chair
- unverified role claim
- manager but not chair
- historical deputy role

Query latency was roughly 0.13-0.26 s in the hard-negative run. The smallest top-1 margin was only 0.020648 for the current-chair query, so production RAG should combine embeddings with explicit date/status/source metadata rather than relying on vector similarity alone.

## Hosted endpoint availability

Observed service-level errors include:

- HTTP 503 Service Unavailable / `ResourceExhausted`, especially on Super/Omni during some periods
- HTTP 529 `Service temporarily overloaded`, repeatedly observed on Gemma
- read timeouts on some long Lightning and Omni calls
- large run-to-run latency variation even for identical or similar requests

These are tracked separately from semantic quality. A dedicated sequential-plus-small-burst reliability suite is still pending.

## Pending benchmark suites

- repeated consistency tests for negation/double-negation and temporal language
- competitive tool routing: registry vs web search vs internal semantic search vs no tool
- hosted reliability/burst metrics: first-attempt success, retry recovery, status codes, median and p95 latency
- source-conflict/evidence synthesis with explicit supporting source IDs
- Norwegian company/register terminology
- further isolated Omni visual arithmetic if hosted availability permits

## Current routing hypothesis

This is provisional and must be updated as pending suites complete:

- **Fast workhorse / simple extraction / tool agent:** Lightning, with validation and escalation on difficult language or malformed JSON.
- **General planner / long-context synthesis:** Super.
- **Hard verification / difficult Norwegian reasoning:** Ultra.
- **High-precision vision/OCR:** Gemma, especially where exact characters matter, but never use it as the sole calculator for financial tables.
- **Fast multimodal extraction:** Omni, with verification for exact identifiers and availability-aware fallback.
- **Retrieval embeddings:** Nemotron 3 Embed 1B plus temporal/status/source metadata filters.

Do not turn this into a single combined leaderboard. Analysen needs task-specific routing, and service availability must remain distinct from model intelligence/quality.
