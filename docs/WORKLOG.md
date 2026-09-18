# Worklog

Kort, append-only oversikt over fullførte milepæler. Dette er ikke en ny TODO-liste; aktive oppgaver hører hjemme i `TASK_QUEUE.md`.

## 2026-09-17
- Etablert scope-first investigation design i `INVESTIGATION_SCOPE.md`: valgfrie research-moduler, expansion policy, materialitet og relation depth.
- Etablert trigger-driven research design i `SEARCH_TRIGGERS.md`: søketriggere, query classes, source routing, verifier-retry, stop rules og coverage ledger.
- Opprettet canonical AI-agent task queue med eksplisitt `READY/IN_PROGRESS/BLOCKED/DONE/CANCELLED`-flyt og definition of done.
- Synkronisert canonical docs, README og AGENTS med scope-first/trigger-driven design; AQ-003 lukket som `DONE`.

## 2026-09-18
- Implementert rettighetsbevisst Nasjonalbiblioteket-adapter for katalog/fulltekstsøk, item-oppslag og gated OCR-fragmenter, med typed modeller og kontrakttester for både åpent og begrenset materiale.
- Kartlagt og source-konfigurert norske offentlige kilder for finansielle konsesjoner, IP, anskaffelser, offentlig journal, arbeidslivsgodkjenninger, bygg, adresser, mattilsyn, fartøy, luftfartøy, tilskudd og petroleum; uimplementerte kilder er eksplisitt disabled candidates.
- Oppdatert source routing og ADR-011 slik at NB-metadata kan brukes til discovery/bibliografisk evidence mens innholdscapture er styrt av per-item accessInfo.
- Ryddet eksisterende Ruff-blokkere som hindret pytest fra å kjøre; branch CI verifisert grønn med ruff, full pytest og Next.js build før AQ-008 ble lukket.
