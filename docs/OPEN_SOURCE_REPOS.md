# Open-source prosjekter av interesse

Disse er referanser/komponentkandidater, ikke alle obligatoriske runtime-avhengigheter.

## Datamodell og entity matching
- FollowTheMoney — https://github.com/alephdata/followthemoney — ontology for personer, selskaper, assets og relasjoner. Sterk inspirasjon/interoperabilitet.
- OpenSanctions yente — https://github.com/opensanctions/yente — FollowTheMoney-basert search/matching. Kan evalueres som separat entity-matching service.
- OpenSanctions API/data — https://www.opensanctions.org/docs/api/ — nyttig screening/search; datasettlisens må vurderes, særlig kommersiell bruk.

## Search/crawling
- SearXNG — https://github.com/searxng/searxng — self-hosted metasearch/discovery.
- Crawl4AI — https://github.com/unclecode/crawl4ai — primær LLM-vennlig crawlerkandidat.
- Trafilatura — https://github.com/adbar/trafilatura — rask main-content extraction.
- Playwright Python — https://github.com/microsoft/playwright-python — JS-browser fallback.
- Firecrawl — https://github.com/firecrawl/firecrawl — self-hostable crawler/extraction-alternativ; ikke nødvendig parallelt med Crawl4AI i MVP.

## Deep research / OSINT referansearkitektur
- GPT Researcher — https://github.com/assafelovic/gpt-researcher — research-loop, report/citations; referanse, ikke canonical architecture.
- SpiderFoot — https://github.com/smicallef/spiderfoot — stor modulbase og korrelasjonsidéer; kilde-/adapterinspirasjon.

## Dokumenter / undersøkende journalistikk
- ICIJ Datashare — https://github.com/ICIJ/datashare — dokumentindeksering, NER, fulltekst og investigative workflows.

## Valgfrie OSINT-moduler
- Maigret — https://github.com/soxoj/maigret — username discovery; kun candidate leads, aldri identitetsbevis.
- OWASP Amass — https://github.com/owasp-amass/amass — passiv virksomhets-/domeneasset discovery når scoped.
- subfinder — https://github.com/projectdiscovery/subfinder — passiv subdomain discovery.
- theHarvester — https://github.com/laramies/theHarvester — passive kilder. Aktive sikkerhetsmoduler er utenfor default scope.

## Agentframeworks — evaluer senere
- PydanticAI — https://github.com/pydantic/pydantic-ai — typed agents/tools/output.
- LangGraph — https://github.com/langchain-ai/langgraph — stateful graph workflows.

MVP bruker egen eksplisitt orchestrator + Pydantic. Frameworket skal ikke bli arkitekturen.

## Ikke anbefalt som canonical base
`alephdata/aleph` er historisk relevant, men vi låser ikke prosjektet til Aleph-applikasjonen. FollowTheMoney-konseptene er mer relevante for vår egen stack.
