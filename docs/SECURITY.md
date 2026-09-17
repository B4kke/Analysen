# Sikkerhet

## Trust boundaries
Nettinnhold og dokumenter er alltid `UNTRUSTED_DATA`. Instruksjoner i kilder skal aldri behandles som system/tool-instruksjoner.

## Prompt injection
- strip scripts/styles/hidden UI der mulig
- marker kildeinnhold eksplisitt som untrusted
- research modeller får smale allowlisted tools
- ingen secrets i prompts
- tool arguments valideres server-side

## SSRF/egress
Blokker loopback, private nett, link-local, cloud metadata, ikke-http(s) og DNS rebinding. Revalider redirects. Bruk egress proxy/network policy i produksjon.

## Secrets
Kun env/secret store. Aldri commit `.env`. Redact i logs. NIM key og eventuelle provider keys har minst mulige rettigheter.

## Files
MIME sniffing, størrelsesgrenser, decompression limits, archive bomb protection og sikker tempdir. Ikke execute dokumentinnhold.

## Authorization
Investigations og rå evidence kan inneholde persondata. Krev autentisering før systemet eksponeres utenfor lokal maskin. Rollebasert tilgang og audit log før flerbrukerdrift.

## Supply chain
Pin lockfiles, Dependabot/Renovate senere, CI lint/test, ingen ukritisk kjøring av kode hentet av agenten.
