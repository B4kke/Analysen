# Agent orchestration

## Roller, ikke permanente personas
- **Planner:** velger neste beste handling innen aktivt scope.
- **Registry worker:** kjører strukturerte registertools.
- **Web researcher:** søk/fetch innen scope.
- **Extractor:** mapper dokument -> typed facts/claims.
- **Lead generator:** lager begrunnede nye spor.
- **Entity resolver:** vurderer kandidater med deterministiske features.
- **Trigger evaluator:** avgjør om et funn, gap eller contradiction skal bli nytt research-lead eller STOP.
- **Verifier:** evidence entailment/contradiction og strukturert missing-information-behov.
- **Financial analyst:** tolker kodeberegnede regnskapstall når `FINANCIALS` er aktiv.
- **Reporter:** skriver kun fra verified claim store + module coverage.

## Scope first
Planner mottar eksplisitt `scope`, `expansion_policy`, `max_relation_depth` og module state. Ingen agent kan utvide dette implisitt.

En nyoppdaget person/virksomhet blir normalt `CONTEXT_ONLY`. Videre research krever reglene i `INVESTIGATION_SCOPE.md`.

## Tool contract
Tool calls er typed og allowlisted. Ingen generisk shell/tool execution fra research-modellen.

Hver action skal inneholde:
- `scope_area`,
- `originating_lead_id`,
- `information_need`,
- `reason`,
- `expected_information_gain`,
- forventet confirm/disconfirm-resultat der relevant.

Scheduler håndhever scope/policy/budget før execution. Agentens begrunnelse er ikke autorisasjon.

## Frontier
Planner får target, compact graph summary, active scope/module state, expansion policy, open leads, completed actions, coverage, budgets og source capabilities. Den returnerer begrunnede actions.

Prioritet skal belønne:
- identitetsavklaring,
- material claims med manglende evidens,
- contradictions,
- høy informasjonsverdi,
- primærkilder.

Prioritet skal nedjustere:
- svak relasjon,
- gjentatte queries,
- context-only entities,
- allerede godt dekkede spørsmål.

## Trigger evaluator
Canonical trigger classes og stop rules ligger i `SEARCH_TRIGGERS.md`.

Trigger evaluator kan returnere:
- `FOLLOW_UP_LEAD`,
- `VERIFICATION_LEAD`,
- `CONTEXT_ONLY`,
- `BLOCKED_BY_SCOPE`,
- `STOP_SUFFICIENT`,
- `STOP_LOW_VALUE`,
- `STOP_BUDGET`.

## Verifier feedback loop
Verifier vurderer claims mot konkret evidence. For `PARTIALLY_SUPPORTED`, `CONTRADICTED` eller `INSUFFICIENT_EVIDENCE` kan den returnere strukturert `missing_information`.

Dette blir bare nytt lead dersom trigger evaluator godkjenner scope, materialitet, dedup og budsjett. Verifier skal ikke starte fri webresearch direkte.

## Stop conditions
- information need besvart,
- max depth / max relation depth,
- max URLs/domain,
- max total documents,
- max model calls/tokens,
- max elapsed time,
- ingen nye high-value leads,
- repeated query/result loop,
- scope/expansion policy blokkerer videre research,
- nødvendig kilde krever forbudt bypass,
- entity forblir eksplisitt `UNRESOLVED` etter relevante kilder.

## Hypoteser
Et lead kan bli hypothesis med `support_needed` og `disconfirm_needed`. Agenten skal aktivt søke etter motbevis når en kobling er vesentlig. Confirmation bias er en eksplisitt eval-feil.

## Coverage
Hver scope-modul fører coverage ledger med sources/providers, query classes, counts, tidsrom, gaps og stop reason. Planner bruker dette for å unngå både premature stopp og meningsløs repetisjon.

## Checkpointing
Hvert tool-resultat, scope/module transition og state transition committes før neste steg. Jobben skal kunne resumeres etter restart uten dobbeltfetch.
