# Testing og evaluering

## Unit
Normalization, URL canonicalization, financial formulas, policy, confidence components.

## Source contract
Recordede offentlige fixtures for BRREG schema og regnskapsmetadata. Live smoke tests separat og rate-begrenset.

## Entity resolution gold set
Navnebrødre, ulike fødselsdatoer, navnevarianter, samme kommune, historiske roller, virksomhetsbytter. Hovedmål: svært lav false-positive merge rate.

## LLM evals (norsk)
- structured extraction F1
- JSON/schema validity
- Norwegian names/letters
- tool-call validity
- claim/evidence entailment
- contradiction detection
- refusal to guess when evidence missing
- prompt-injection resistance

## Hallucination test
Spør om attributt som ikke finnes i evidence. Forvent `INSUFFICIENT_EVIDENCE`, aldri gjetning.

## Citation gate
Hver material report claim må ha minst én evidence link; verifier skal kontrollere entailment før report state kan bli REVIEWED.

## Security
SSRF, redirects, DNS rebinding, malicious HTML instructions, archive bombs, oversized docs og secrets redaction.
