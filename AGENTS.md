# AGENTS.md — autoritativ arbeidsinstruks

## Oppdrag
Bygg Analysen som en norsk, kildebevisst OSINT-motor. Systemet skal undersøke personer og virksomheter ved hjelp av lovlig tilgjengelige åpne kilder, følge nye spor, verifisere påstander og produsere etterprøvbare rapporter.

## Ikke-forhandlingsbare regler
1. **Ingen påstand uten evidens.** Vesentlige rapportpåstander skal peke til lagret evidence med URL, hentetid, kilde og relevant tekst/strukturert felt.
2. **LLM er ikke sannhetsdatabase.** Modeller planlegger, ekstraherer, foreslår og skriver. Deterministisk kode lagrer, normaliserer, beregner og håndhever policy.
3. **Discovery er ikke evidence.** Søkeresultatsnutter brukes kun for å finne kilden. Originalsiden/dokumentet må hentes før en påstand kan støttes.
4. **Identitetslikhet er ikke identitet.** Samme navn alene må aldri slå sammen personer. Fødselsdato, rollehistorikk, lokasjon, selskaper og tidslinje skal vurderes eksplisitt.
5. **Primærkilder først.** Brønnøysund og andre offisielle registre prioriteres foran medier og tilfeldige nettsteder.
6. **Ingen omgåelse.** Ikke omgå innlogging, CAPTCHA, betalingsmur, robots/rate-begrensning, privat API eller tilgangskontroll.
7. **Ingen sensitive inferenser.** Ikke inferer helse, religion, etnisitet, seksuell orientering eller politiske meninger. Politiske registerdata skal være deaktivert som standard.
8. **Straffedata er særskilt.** Systemet skal ikke bygge et omfattende straffedomregister. Slike data er deaktivert som standard og krever særskilt juridisk vurdering.
9. **Ingen person-risikoscore.** Presenter dokumenterte funn, usikkerhet og motstrid; ikke en svart-boks score over en persons «risiko».
10. **Ingen sletting av funksjoner for å få tester grønne.** Reparer årsaken.

## Arkitektur
- `apps/api`: FastAPI og domene-API.
- `apps/web`: Next.js brukerflate.
- `apps/worker`: asynkrone research-jobs.
- `config`: modell-, kilde- og policykonfigurasjon.
- `prompts`: versjonerte LLM-kontrakter.
- `db`: canonical schema/migrations.
- `docs`: autoritativ design og beslutninger.

PostgreSQL er canonical store. pgvector er et retrieval-indeks, ikke sannhetskilde. Redis er kø/cache. SearXNG brukes for discovery. Crawl4AI/Trafilatura/Playwright brukes til nettsider. BRREG er første norske registerintegrasjon.

## Arbeidsrekkefølge
1. Les `docs/IMPLEMENTATION_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/PRIVACY_LEGAL.md` og relevante spesifikasjoner.
2. Fullfør én vertikal oppgave før neste startes.
3. Implementer typed schemas før agentlogikk.
4. Implementer source adapters med fixtures og kontrakttester.
5. Lagre raw evidence før LLM-ekstraksjon.
6. Valider alle LLM-utdata mot Pydantic/JSON schema.
7. Kjør entity-resolution og provenance-gates før rapportering.
8. Oppdater `docs/DECISIONS.md` når arkitektur endres.

## Kvalitetsporter
En feature er ikke ferdig før:
- den har strukturert logging,
- feiltilstander er eksplisitte,
- datakilde og lisens/tilgangstype er dokumentert,
- LLM-resultater valideres,
- relevante unit/contract tests finnes,
- rapportpåstander kan spores til evidence,
- sikkerhets- og personvernregler ikke omgås.

## Modellbruk
Modellvalg er konfigurasjon. Hardkod aldri modellnavn i business logic. Se `config/models.yaml` og `docs/NIM_MODELS.md`. Norske tekstoppgaver må evalueres i prosjektets norske eval-sett; NVIDIA Nemotron-modellkortene lister ikke norsk som offisielt støttet språk.

## Forbudte snarveier
- Fake/mock research i produksjonsflyt.
- Hardkodede rapporter.
- Regex som eneste entity resolver.
- LLM confidence som eneste confidence-kilde.
- Automatisk sammenslåing ved navnelikhet.
- Påstander fra snippets.
- Ubegrenset crawling.
- Loggføring av secrets eller unødvendige personopplysninger.
