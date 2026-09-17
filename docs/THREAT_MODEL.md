# Threat model

## Assets
NIM key, investigation data, rå snapshots, persondata, reports, database, crawler network access.

## Adversaries/failures
- ondsinnet nettside med prompt injection
- SSRF mot lokalnett/cloud metadata
- poisoned search results
- feil person koblet pga navnelikhet
- LLM hallucination
- source schema drift
- lekkasje av secrets i logs/prompts
- overinnsamling av persondata
- bruker som forsøker å aktivere forbudte/restricted sources

## Mitigations
Typed tools, untrusted-content boundary, egress guard, provenance gates, conservative identity resolver, source schema tests, secrets redaction, policy engine, budgets, audit log og human review.

## Abuse resistance
Ingen credential/breach dumps, privat kontotilgang, CAPTCHA bypass, skjult lokasjonssporing eller aktive nettverksangrep. Passive domeneverktøy er optional og scoped til virksomhetsinfrastruktur.
