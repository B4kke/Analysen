# Case management

## Formål
Et Case grupperer flere related investigations uten å blande evidens eller identiteter ukritisk.

```text
Case
├── Investigation: Person A
├── Investigation: Company B
└── Investigation: Domain C
```

## Regler
- Hver investigation beholder eget target, purpose, budgets og report state.
- Verified entities kan refereres på tvers av investigations, men en kobling må fortsatt ha evidence i riktig kontekst.
- Uverifiserte leads skal ikke «smitte» andre investigations som fakta.
- Case graph er en projection av dokumenterte entities/relationships.
- Manual annotations får author/timestamp/audit.

## Senere schema
`cases(id, title, purpose, created_at, retention_until)` og `case_investigations(case_id, investigation_id)`.

## UI
Case overview viser targets, timeline, shared entities, contradictions og rapporter. Dette kommer etter single-investigation MVP.
