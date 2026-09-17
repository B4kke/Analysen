# Datamodell

## Hovedobjekter
### Investigation
`id, target_type, purpose, legal_basis_note, status, created_by, budgets, created_at, retention_until`.

### Entity
`id, schema, canonical_name, normalized_name, attributes_json, status, created_at`.
Schemas: Person, Organization, Company, Address, Domain, Document, Event.

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
`type, entity/value, reason, originating_claim_id, priority, depth, status`.

### Contradiction
Kobler claims/evidence som er logisk eller temporalt uforenlige.

### InvestigationEvent/AuditLog
Append-only operasjonell og sikkerhetsmessig historikk.

## FollowTheMoney
Bruk FollowTheMoney-skjemaer/terminologi som referanse for interoperabilitet, men behold en intern relasjonell canonical modell som støtter provenance på felt- og claimnivå. Ikke bind databaseformatet direkte til én ekstern pakke.

Repo: https://github.com/alephdata/followthemoney
