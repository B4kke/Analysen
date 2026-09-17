# Testing og evaluering

## Unit
Normalization, URL canonicalization, financial formulas, policy, confidence components, scope gates, expansion policy og trigger selection.

## Source contract
Recordede offentlige fixtures for BRREG schema og regnskapsmetadata. Live smoke tests separat og rate-begrenset.

## Entity resolution gold set
Navnebrødre, ulike fødselsdatoer, navnevarianter, samme kommune, historiske roller, virksomhetsbytter. Hovedmål: svært lav false-positive merge rate.

Test også at identity resolution ikke åpner full research av relaterte entities uten aktivt scope.

## Scope-gate tests
Obligatoriske cases:
- deaktivert modul kan aldri planlegges/kalles,
- globalt enabled source er ikke nok uten aktivt scope,
- `CONTEXT_ONLY` entity auto-ekspanderes ikke,
- `DIRECT_RELATIONS` respekterer relation depth,
- `MATERIAL_RELATIONS` krever eksplisitt material reason/information need,
- scope-utvidelse åpner relevante leads og auditeres,
- scope-innsnevring stopper nye actions.

## Search-trigger evals
Obligatoriske cases:
- `IDENTITY_AMBIGUITY` velger målrettet resolution fremfor bred research,
- `WEAK_SOURCE_ONLY` søker sterkere/uavhengig kilde,
- `CONTRADICTION` lager disconfirmation lead,
- `TEMPORAL_GAP` velger tids-/historikkilder,
- `DOCUMENT_QUALITY` prøver parser/OCR/VLM før irrelevant websearch,
- `FINANCIAL_ANOMALY` trigges bare når FINANCIALS er aktiv og entity er target/material,
- repeated query/result loop stopper,
- ingen nye high-value leads gir stop.

## LLM evals (norsk)
- structured extraction F1
- JSON/schema validity
- Norwegian names/letters
- tool-call validity
- scope/tool routing validity
- claim/evidence entailment
- contradiction detection
- refusal to guess when evidence missing
- prompt-injection resistance
- confirmation-bias/disconfirm behavior

## Hallucination test
Spør om attributt som ikke finnes i evidence. Forvent `INSUFFICIENT_EVIDENCE`, aldri gjetning.

## Citation gate
Hver material report claim må ha minst én evidence link; verifier skal kontrollere entailment før report state kan bli REVIEWED.

## Coverage/report tests
Rapportgenerator skal korrekt skille:
- undersøkt,
- undersøkt med gaps,
- ikke undersøkt,
- blokkert/utilgjengelig.

Ikke-valgt modul skal aldri omtales som «ingen funn».

## Security
SSRF, redirects, DNS rebinding, malicious HTML instructions, archive bombs, oversized docs og secrets redaction.

## Repo-hygiene gate
En oppgave skal ikke markeres `DONE` før relevante docs/tests er synkronisert. CI/lint kan senere kontrollere at kjente TODO/FIXME følger en task-ID eller eksplisitt policy.
