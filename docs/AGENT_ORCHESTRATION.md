# Agent orchestration

## Roller, ikke permanente personas
- **Planner:** velger neste beste handling.
- **Registry worker:** kjører strukturerte registertools.
- **Web researcher:** søk/fetch innen scope.
- **Extractor:** mapper dokument -> typed facts/claims.
- **Lead generator:** lager begrunnede nye spor.
- **Entity resolver:** vurderer kandidater med deterministiske features.
- **Verifier:** evidence entailment/contradiction.
- **Financial analyst:** tolker kodeberegnede regnskapstall.
- **Reporter:** skriver kun fra verified claim store.

## Tool contract
Tool calls er typed og allowlisted. Ingen generisk shell/tool execution fra research-modellen.

## Frontier
Planner får target, compact graph summary, open leads, completed actions, budgets og source capabilities. Den returnerer begrunnede actions. Scheduler håndhever policy og budsjetter før execution.

## Stop conditions
- max depth
- max URLs/domain
- max total documents
- max model calls/tokens
- max elapsed time
- ingen nye high-value leads
- repeated query/result loop

## Hypoteser
Et lead kan bli hypothesis med `support_needed` og `disconfirm_needed`. Agenten skal aktivt søke etter motbevis når en kobling er vesentlig.

## Checkpointing
Hvert tool-resultat og state transition committes før neste steg. Jobben skal kunne resumeres etter restart uten dobbeltfetch.
