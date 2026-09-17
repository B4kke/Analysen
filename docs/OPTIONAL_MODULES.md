# Valgfrie OSINT-moduler

Disse kommer etter norsk register/web-kjerne og er **ikke** nødvendige for MVP.

## Maigret
Kun når et kjent offentlig brukernavn er et legitimt lead. Treff importeres som candidate profiles med svak identity weight. Ingen automatisk kobling til målperson.

## Amass / subfinder / theHarvester
Kun passive moduler for virksomhetsdomener/infrastruktur. Formål: forstå offentlig selskapsweb/infrastruktur, ikke vulnerability scanning. Ingen portscan, exploit eller credential probing.

## SpiderFoot
Bruk som kilde-/korrelasjonsreferanse eller isolert optional adapter. Ikke la SpiderFoot-resultater bli claims uten normal Evidence pipeline.

## Firecrawl
Kan evalueres som alternativ crawler-provider. Ikke kjør Firecrawl og Crawl4AI som to parallelle canonical pipelines uten målt gevinst.

## yente
Kan brukes til lokal entity matching over egne FollowTheMoney-data eller lisensierte OpenSanctions-data. Se `docs/OPENSANCTIONS.md`.

## Neo4j/Memgraph
Kun graph projection dersom PostgreSQL recursive queries blir en reell flaskehals. PostgreSQL forblir canonical.

## OpenSearch
Aktuelt dersom fulltekstsøk/yente/document corpus vokser betydelig. Ikke nødvendig for første norske MVP.

## MinIO/S3
Aktuelt når raw evidence flyttes fra lokalt volum til objektlager. Content hash/provenance-format beholdes uendret.
