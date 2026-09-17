# Datamodell

## Hovedobjekter
### Investigation
`id, target_type, purpose, legal_basis_note, scope, expansion_policy, max_relation_depth, status, created_by, budgets, created_at, retention_until`.

`scope` er eksplisitte moduler fra `INVESTIGATION_SCOPE.md`. Source availability er separat og styres av `config/sources.yaml`.

### InvestigationModule
Per investigation/scope-modul:
`investigation_id, module, enabled, status, coverage_json, stop_reason, started_at, completed_at`.

`coverage_json` inneholder providers/kilder forsøkt, query classes, counts, tidsrom, kjente gaps og utilgjengelige kilder.

### Entity
`id, schema, canonical_name, normalized_name, attributes_json, status, created_at`.
Schemas: Person, Organization, Company, Address, Domain, Document, Event.

### InvestigationEntity
Kobler entity til investigation med `relevance`, `relation_depth`, `expansion_state`, `material_reason` og discovery metadata.

`expansion_state`: `TARGET`, `MATERIAL`, `CONTEXT_ONLY`, `BLOCKED`, `RESEARCHED`.

### EntityAlias
Originale navn, historiske navn og normaliserte varianter med source/evidence.

### Relationship
`subject_entity_id, predicate, object_entity_id, start_date, end_date, confidence_state` + evidence links.
Predicates: DIRECTOR_OF, CEO_OF, AUDITOR_OF, ACCOUNTANT_OF, MEMBER_OF, PARENT_OF, SUBSIDIARY_OF, REGISTERED_AT, SAME_ADDRESS_AS, OPERATES_DOMAIN, MENTIONED_IN.

### Source
Adapter/kilde metadata, authority tier, access class, URL/license.

### Document
Original URL, canonical URL, MIME, fetched_at, published_at, content hash, raw storage key, extracted text pointer, parser metadata.

### Evidence
Minste relevante kildeenhet: dokumentpassasje, JSONPath/felt, tabellcelle eller bilde-region. Evidence beholder source/document og locator.

### Claim
`subject, predicate, object/value, temporal_context, status, confidence_components, generated_by`.
Status: `SUPPORTED`, `PARTIALLY_SUPPORTED`, `CONTRADICTED`, `INSUFFICIENT_EVIDENCE`, `UNVERIFIED_LEAD`.

### ClaimEvidence
M:N mellom claim/evidence med relation=`supports|contradicts|context`.

### Lead
`type, entity/value, reason, originating_claim_id, scope_area, trigger_type, information_need, priority, depth, relation_depth, status, blocked_reason`.

Et lead uten aktiv scope-modul eller tillatt expansion policy kan eksistere som observasjon, men får `BLOCKED`/`CONTEXT_ONLY` og skal ikke eksekveres.

### SearchQuery
`investigation_id, originating_lead_id, scope_area, query_class, intent, provider, query, query_hash, reason, created_at`.

Dette gjør det mulig å forklare hvorfor et søk ble kjørt og å stoppe repeated query/result loops.

### Contradiction
Kobler claims/evidence som er logisk eller temporalt uforenlige.

### InvestigationEvent/AuditLog
Append-only operasjonell og sikkerhetsmessig historikk. Scope-endringer, materiality-markeringer, manuelle merge/split og expansion decisions skal auditeres.

## Scope og expansion
Canonical regler ligger i `INVESTIGATION_SCOPE.md`.

Source enabled != source authorized for current investigation. En source kan være globalt tilgjengelig uten at relevant scope-modul er aktivert.

## Coverage og negative funn
Coverage state er eksplisitt data, ikke fri rapportprosa. Report-generatoren bruker module coverage til å skille:
- undersøkt og fullført,
- undersøkt med gaps,
- ikke undersøkt,
- blokkert/utilgjengelig.

## FollowTheMoney
Bruk FollowTheMoney-skjemaer/terminologi som referanse for interoperabilitet, men behold en intern relasjonell canonical modell som støtter provenance på felt- og claimnivå. Ikke bind databaseformatet direkte til én ekstern pakke.

Repo: https://github.com/alephdata/followthemoney
