# AGENTS.md — autoritativ arbeidsinstruks

## Oppdrag
Bygg Analysen som en norsk, kildebevisst OSINT-motor. Systemet skal undersøke personer og virksomheter ved hjelp av lovlig tilgjengelige åpne kilder, følge relevante spor innen eksplisitt valgt scope, verifisere påstander og produsere etterprøvbare rapporter.

## Source of truth
Før arbeid skal agenten lese:
1. `docs/TASK_QUEUE.md` — kanonisk arbeidskø og status.
2. `docs/IMPLEMENTATION_PLAN.md` — leveransefaser.
3. `docs/ARCHITECTURE.md` — systemarkitektur.
4. `docs/INVESTIGATION_SCOPE.md` — hva en investigation får undersøke.
5. `docs/SEARCH_TRIGGERS.md` — når/hvorfor systemet får søke videre.
6. `docs/PRIVACY_LEGAL.md` — juridiske/personvernmessige grenser.
7. `docs/NATIONAL_LIBRARY.md` — canonical kontrakt for Nasjonalbiblioteket/DH-lab/IIIF når NB/media berøres.
8. relevante domene-/kildedokumenter for oppgaven.

Ikke opprett parallelle TODO-lister i tilfeldige filer. Nye oppgaver føres i `docs/TASK_QUEUE.md`. Fullførte milepæler føres kort i `docs/WORKLOG.md`.

## Ikke-forhandlingsbare regler
1. **Ingen påstand uten evidens.** Vesentlige rapportpåstander skal peke til lagret evidence med URL, hentetid, kilde og relevant tekst/strukturert felt.
2. **LLM er ikke sannhetsdatabase.** Modeller planlegger, ekstraherer, foreslår og skriver. Deterministisk kode lagrer, normaliserer, beregner og håndhever policy.
3. **Discovery er ikke evidence.** Søkeresultatsnutter brukes kun for å finne kilden. Originalsiden/dokumentet må hentes før en påstand kan støttes.
4. **Discovery er ikke autorisasjon til å ekspandere.** En ny entity kan lagres som kontekst, men videre research krever aktiv scope-modul, tillatt expansion policy, konkret information need og tilgjengelig budsjett/policy.
5. **Identitetslikhet er ikke identitet.** Samme navn alene må aldri slå sammen personer. Fødselsdato, rollehistorikk, lokasjon, selskaper og tidslinje skal vurderes eksplisitt.
6. **Primærkilder først.** Brønnøysund og andre offisielle registre prioriteres foran medier og tilfeldige nettsteder.
7. **Ingen omgåelse.** Ikke omgå innlogging, CAPTCHA, betalingsmur, robots/rate-begrensning, privat API eller tilgangskontroll.
8. **Ingen sensitive inferenser.** Ikke inferer helse, religion, etnisitet, seksuell orientering eller politiske meninger. Politiske registerdata skal være deaktivert som standard.
9. **Straffedata er særskilt.** Systemet skal ikke bygge et omfattende straffedomregister. Slike data er deaktivert som standard og krever særskilt juridisk vurdering.
10. **Ingen person-risikoscore.** Presenter dokumenterte funn, usikkerhet og motstrid; ikke en svart-boks score over en persons «risiko».
11. **Ingen sletting av funksjoner for å få tester grønne.** Reparer årsaken.
12. **Ingen skjult sidearbeid.** Nye funn som ikke hører til aktiv oppgave blir egne queue-items; ikke start dem halvveis.

## Arkitektur
- `apps/api`: FastAPI og domene-API.
- `apps/web`: Next.js brukerflate.
- `apps/worker`: asynkrone research-jobs.
- `config`: modell-, kilde- og policykonfigurasjon.
- `prompts`: versjonerte LLM-kontrakter.
- `db`: canonical schema/migrations.
- `docs`: autoritativ design, beslutninger og oppgavehygiene.

PostgreSQL er canonical store. pgvector er retrieval-indeks, ikke sannhetskilde. Redis er kø/cache. SearXNG brukes for discovery. Crawl4AI/Trafilatura/Playwright brukes til nettsider. BRREG er første norske registerintegrasjon.

## Arbeidsflyt for AI-agenter
1. Velg høyest prioriterte `READY`-oppgave uten blocker i `docs/TASK_QUEUE.md`.
2. Sett den `IN_PROGRESS` før større arbeid starter.
3. Les alle canonical docs som oppgaven berører før endring.
4. Fullfør én vertikal oppgave før neste startes.
5. Implementer typed schemas før agentlogikk.
6. Implementer source adapters med fixtures og kontrakttester.
7. Lagre raw evidence før LLM-ekstraksjon.
8. Valider alle LLM-utdata mot Pydantic/JSON schema.
9. Kjør scope-gate, entity-resolution og provenance-gates før videre research/rapportering.
10. Hvis en reell blocker oppstår, sett oppgaven `BLOCKED` og dokumenter nøyaktig blocker.
11. Når acceptance criteria er oppfylt: sett `DONE`, oppdater relevante docs/tests og append kort linje i `WORKLOG.md`.
12. Oppdater `docs/DECISIONS.md` når arkitektur eller ufravikelige designvalg endres.

## Definition of done
En feature/oppgave er ikke ferdig før:
- avtalt scope er fullført uten skjulte halvferdige sidegrener,
- strukturert logging og eksplisitte feiltilstander finnes der relevant,
- datakilde og lisens/tilgangstype er dokumentert,
- LLM-resultater valideres,
- relevante unit/contract/eval-tester finnes eller manglende kjørbarhet er eksplisitt dokumentert,
- rapportpåstander kan spores til evidence,
- sikkerhets- og personvernregler ikke omgås,
- relevante source-of-truth docs er synkronisert,
- nye oppfølgingsbehov er egne queue-items,
- oppgaven er markert `DONE` i `TASK_QUEUE.md`.

## Modellbruk
Modellvalg er konfigurasjon. Hardkod aldri modellnavn i business logic. Se `config/models.yaml` og `docs/NIM_MODELS.md`. Norske tekstoppgaver må evalueres i prosjektets norske eval-sett; modellkort alene er ikke tilstrekkelig kvalitetsbevis.

## Forbudte snarveier
- Fake/mock research i produksjonsflyt.
- Hardkodede rapporter.
- Regex som eneste entity resolver.
- LLM confidence som eneste confidence-kilde.
- Automatisk sammenslåing ved navnelikhet.
- Påstander fra snippets.
- Ubegrenset crawling.
- Automatisk full research av enhver nyoppdaget person/virksomhet.
- Loggføring av secrets eller unødvendige personopplysninger.


## OpenCode2: subagent-first arbeidsmodell

Prosjektet er konfigurert for OpenCode2 via `opencode.jsonc`, `.opencode/agents/` og `.opencode/skills/`.

### Delegasjon er standard på komplekst arbeid
For oppgaver som berører flere lag, flere filer, migreringer, research-runtime, backend+frontend eller P0-integrasjon skal primæragenten normalt delegere til flere subagents i stedet for å gjøre alt sekvensielt selv.

- Start 2–5 subagents samtidig når arbeidsstrømmene er reelt uavhengige.
- Gi hver subagent eksplisitt subsystem-/fileierskap og acceptance criteria.
- Ikke la to subagents skrive til samme migrasjon, schema-kontrakt eller felles integrasjonsfil samtidig.
- `docs/TASK_QUEUE.md`, `docs/WORKLOG.md` og `docs/DECISIONS.md` eies normalt av orchestrator/integrator.
- Kjør `integration-reviewer` før P0 settes `DONE`.
- En subagents egen "ferdig"-melding er aldri tilstrekkelig; orchestrator må kontrollere diff og kjøre integrert verifikasjon.

Primær OpenCode2-agent er `analysen-orchestrator`. Se `docs/RECOVERY_ACTION_PLAN.md` for delegert rekkefølge og wave-plan.

### Tilgjengelige prosjektagenter
- `db-provenance`
- `research-runtime`
- `nb-media`
- `research-orchestration`
- `entity-resolution`
- `verification`
- `ui-reporting`
- `integration-reviewer`

### Skill-bruk
Agenter skal laste relevante prosjekt-skills fra `.opencode/skills/` før de endrer et subsystem. Skill-instruksjoner supplerer dette dokumentet, men kan aldri overstyre scope-, provenance-, privacy- eller safety-reglene over.
