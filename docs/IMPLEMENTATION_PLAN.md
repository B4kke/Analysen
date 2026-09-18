# Konkret implementasjonsplan

## Målbilde
En bruker oppretter en investigation med navn, eventuelt fødselsdato/år, sted og kjente virksomheter, og velger eksplisitt hvilke bakgrunnssjekk-områder som skal undersøkes. Analysen identifiserer målpersonen/-virksomheten, bruker bare relevante kilder innen valgt scope, bygger dokumenterte relasjoner, følger nye spor når trigger-reglene tilsier det, verifiserer koblinger og produserer en rapport der hver vesentlige påstand kan åpnes tilbake til kilden.

Canonical kontrakter:
- `INVESTIGATION_SCOPE.md`: hva investigation får undersøke.
- `SEARCH_TRIGGERS.md`: når/hvorfor den får søke videre.
- `TASK_QUEUE.md`: aktiv arbeidskø for implementasjon.

## Fase 0 — grunnmur
**Leveranser**
- monorepo-struktur
- Docker Compose
- FastAPI health/config
- PostgreSQL + pgvector
- Redis
- Next.js shell
- typed domain schemas
- NIM provider abstraction
- source adapter interface
- policy engine

**Exit:** `docker compose up` starter basistjenestene, API svarer health, database kan migreres, modell- og source-config valideres.

## Fase 1 — norsk registerkjerne
Implementer i denne rekkefølgen:
1. BRREG entity search/oppslag.
2. BRREG roller per orgnr.
3. BRREG åpen `roller/totalbestand` som periodisk bulkimport.
4. Lokal reverse-index: normalisert personnavn + fødselsdato -> roller/virksomheter.
5. BRREG juridiske roller for virksomhet -> andre virksomheter.
6. BRREG konsernstruktur.
7. Historiske navn/statusfelt.
8. Regnskapsregisteret: tilgjengelige år + PDF-kopi.

**Exit:** gitt en norsk person med nok identifikatorer kan systemet vise dokumenterte virksomhetsroller og relasjoner uten kommersiell tredjeparts-API.

## Fase 2 — evidence, entity resolution og scope contract
- raw-document store med SHA-256
- `Source`, `Document`, `Evidence`, `Claim`, `ClaimEvidence`
- deterministic normalization
- candidate generation
- identity scoring med harde negative signaler
- `MATCH`, `PROBABLE_MATCH`, `UNRESOLVED`, `NOT_MATCH`
- manuell merge/split
- typed `scope_modules`
- `expansion_policy`
- `max_relation_depth`
- `InvestigationModule`/coverage state
- `InvestigationEntity.expansion_state`

**Exit:** samme navn alene kan ikke merge personer. Alle grafkanter har provenance. En deaktivert modul kan ikke autorisere research.

## Fase 3 — web research/discovery
- SearXNG discovery
- URL canonicalization/dedup
- Trafilatura fast path
- Crawl4AI main path
- Playwright fallback
- SSRF/egress guard
- robots/rate/domain budgets
- Common Crawl/RDAP adapters
- søkehistorikk og query dedup
- typed query classes og search metadata
- coverage ledger per modul

**Exit:** discovery-snippets kan aldri bli evidence; rapportering krever hentet originalkilde. Hvert søk kan forklares med originating lead, scope area, query class og reason.

## Fase 4 — agentisk research-loop
- planner
- researcher/workhorse
- lead generator
- trigger evaluator
- verifier
- contradiction detector
- frontier priority queue
- scope/expansion gate før execution
- verifier-triggered missing-information leads
- depth/budget/stop conditions
- checkpoint/resume

**Exit:** funn kan generere nye begrunnede leads, men discovery alene gir ikke auto-ekspansjon. Relaterte entities kan forbli `CONTEXT_ONLY`. Ingen ubegrenset rekursjon.

## Fase 5 — dokument/regnskap
- PDF text/layout extraction
- tabelluttrekk
- OCR/multimodal fallback
- årsregnskapsnormalisering
- deterministiske finansnøkkeltall
- year-over-year-analyse
- noter/revisor/going-concern som claims med evidence
- FINANCIALS scope/materiality gate

**Exit:** tall beregnes i kode, ikke av LLM. Finansanalyse kjøres ikke automatisk for alle company-noder.

## Fase 6 — rapport og UI
Hovedflater:
- New investigation: target, formål, scope, expansion policy og relation depth.
- Investigation: live events, module cards, coverage og budgets.
- Graph: personer/virksomheter/adresser/domener/dokumenter med target/material/context-only state.
- Evidence: claims, støtte, motstrid, kildeviewer.
- Report: draft/reviewed/final.

Rapporten er dynamisk etter valgt scope og viser eksplisitt hvilke områder som er `UNDERSØKT`, `UNDERSØKT_MED_GAPS`, `IKKE_UNDERSØKT` eller `BLOKKERT_UTILGJENGELIG`.

## Fase 7 — kvalitet og sikkerhet
- norske gold fixtures
- source contract tests
- hallucination tests
- citation entailment tests
- false-positive entity-resolution suite
- scope-gate suite
- trigger-routing/no-loop suite
- no-unnecessary-expansion suite
- prompt-injection suite
- SSRF suite
- privacy policy tests
- audit log

## Fase 8 — overvåking/endrede forhold
Kun etter stabil MVP:
- snapshot-to-snapshot diff
- nye roller/status/regnskap innen valgte monitor-moduler
- nye relevante åpne kilder
- endringsrapport

Monitoring arver samme scope/expansion-regler; en monitor skal ikke gradvis utvide saken på egen hånd.

## Prioritert neste arbeid
Aktiv kø er autoritativ i `docs/TASK_QUEUE.md`. Scope/gates, avgrenset BRREG-pass, coverage og dekningsrapport er implementert. Grunnmurreparasjonen omfatter canonical provenance/migrering, guarded web-fetch med komplett research-runtime og readiness mot pakket migreringshead. AQ-025 kobler detaljsiden til lagrede job-, modul-, lead-, entity- og evidensdata. Autonom planner-loop/checkpoint (AQ-023), flere kildetyper (AQ-024), verifier (AQ-026) og full rapport (AQ-027) gjenstår før MVP-bevis (AQ-028).

## Definition of done for MVP
- Norsk person kan identifiseres med eksplisitt usikkerhet.
- Bruker kan velge hvilke research-moduler som skal kjøres.
- Deaktivert modul kan ikke kalles av planner/agent.
- Offentlige virksomhetsroller kan reverssøkes fra lokal BRREG-indeks når relevant scope tillater det.
- Virksomheter, roller, konsern og årsregnskap kan hentes når riktig modul/materialitet tillater det.
- Web discovery og crawling fungerer uten betalt search API.
- Nye funn utløser bare ekstra research gjennom eksplisitte trigger-regler.
- Alle material claims har evidence.
- Rapport skiller bekreftet, delvis støttet, motstridende og utilstrekkelig evidens.
- Rapport viser hva som ikke ble undersøkt og kjente coverage-gaps.
- Ingen sensitiv inferens eller person-risikoscore.
