# Kilde- og runtimegjennomgang 2026-11-21

Baseline: main f2b2063b5a06d7573669616e02bfe7939eea0e87. Statisk inspeksjon; ikke et live-testresultat.

| Rute | Status i kode | Verifikasjon som gjenstår |
|---|---|---|
| BRREG entities | Typed lead executor + direkte API | Live schema/feil og disabled switch i direkte API |
| BRREG roles, index, legal roles, group | Separate API/worker paths | Switch enforcement, ferskhet, rettigheter, live |
| SearXNG | Typed discovery, ikke evidence | Live engines, rate limits, null-resultat vs feil |
| Web | Typed fetch | Policy, redirects, tomt innhold, store dokumenter |
| PDF | Typed processing | OCR, korrupt PDF, provenance |
| NB | Typed media executor | Catalog/DH-lab/IIIF, item rights, null-resultat |
| Common Crawl, GLEIF, GDELT, RDAP, EU sanctions, announcements, accounts | Konfigurerte kilder; ikke egne typed lead routes | Ikke hevde automatisk dekning; avklar adapter/fixture/API-status |

Kildekonfigurasjonen alene er ikke et bevis på fungerende research. Ikke aktiver kandidater før tilgang og kontrakt er dokumentert. Bruk kun syntetiske fixtures eller offentlige virksomheter ved verifikasjon, og behold alle scope-/personvernregler.

Test: eksisterende CI kjører migrations, Ruff, mypy, pytest, Next-build og Playwright i 390 px. Denne gjennomgangen har ikke kjørt dem lokalt (nettverk/kopi utilgjengelig). Se AQ-043/044.


## Oppfølging
Switch-kontroll er også innført ved opptak av kjente lead-typer, direkte BRREG-endepunkter og inventory-refresh. PDF-behandling leser kun hash-verifisert råmateriale; manipulerte dokumenter feiler før ekstraksjon. Opprettelses-GUI beskriver hvilke moduler som ikke har komplett automatisert innhenting. Dette er ikke en live-kildeverifikasjon.
