# Observability

## Strukturert event
Alle jobs/logs bør bære: `investigation_id`, `job_id`, `agent_role`, `tool/source`, `query/action`, `duration_ms`, `result_count`, `model`, `input_tokens`, `output_tokens`, `retry_count`, `error_code`.

## Produktmetrics
- URLs discovered/fetched/deduped
- official records fetched
- entities/candidates/merges/manual reviews
- claims by status
- contradictions
- leads opened/resolved
- citations per material claim
- model calls by role
- source errors/schema drift
- report generation latency

## Audit vs debug logs
Audit er append-only og brukerorientert: hvem gjorde hva med investigation. Debug logger tekniske detaljer og skal redigere persondata/secrets.

## Tracing
Legg senere OpenTelemetry rundt source calls, queue jobs og model calls. Ikke send rå persondata til ekstern telemetry-provider uten eksplisitt vurdering.
